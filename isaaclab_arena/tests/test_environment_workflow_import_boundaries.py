# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Read-only CLI contracts, exercised only in the offline backend sandbox."""

import copy
import hashlib
import json

import pytest


def test_scope_admin_cold_construction_has_no_resource_effects(monkeypatch):
    import builtins
    import importlib.util
    import os
    import sys

    prefix = "isaaclab_arena.agentic_environment_generation.workflow"
    names = (prefix + ".admin", prefix + ".scope_binding")
    saved = {name: sys.modules[name] for name in names if name in sys.modules}
    parents = [(sys.modules.get(name.rpartition(".")[0]), name.rpartition(".")[2]) for name in names]
    attrs = [(parent, attr, vars(parent).get(attr)) for parent, attr in parents if parent is not None]
    forbidden = (
        "sqlite3",
        "openai",
        "anthropic",
        "fastapi",
        "strawberry",
        "neo4j",
        "torch",
        "omni",
        "isaacsim",
        "isaaclab_arena_examples",
        "isaaclab_arena.agentic_environment_generation.workbench.journal",
        "isaaclab_arena.agentic_environment_generation.workbench.research_store",
        "isaaclab_arena.agentic_environment_generation.workbench.research_registry",
    )
    original = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        resolved = importlib.util.resolve_name("." * level + name, globals["__package__"]) if level else name
        assert not any(resolved == item or resolved.startswith(item + ".") for item in forbidden)
        return original(name, globals, locals, fromlist, level)

    class NoEffects:
        def __getattr__(self, name):
            pytest.fail("cold scope admin touched external port: " + name)

    def denied(*args, **kwargs):
        pytest.fail("cold scope admin opened filesystem")

    for name in names:
        sys.modules.pop(name, None)
    for parent, attr, value in attrs:
        vars(parent).pop(attr, None)
    try:
        with monkeypatch.context() as m:
            m.setattr(builtins, "__import__", guarded)
            m.setattr(os, "open", denied)
            from isaaclab_arena.agentic_environment_generation.workflow.admin import WorkflowScopeAdmin
            from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore
            from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding

            no = NoEffects()
            store = Neo4jWorkflowStore(
                no, database="explicit-db", deployment_id="explicit-deployment", workspace_id="explicit-workspace"
            )
            admin = WorkflowScopeAdmin(store, no)
            binding = ScopeBinding(
                database=store.database,
                **store.scope,
                schema_version=1,
                authority_id="explicit-authority",
                operational_schema_version=1,
                artifact_marker_schema=1,
                store_id="explicit-store",
                registry_id="explicit-registry",
            )
            assert admin._store is store and binding.authority_id != binding.store_id
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
        for parent, attr, value in attrs:
            if value is None:
                vars(parent).pop(attr, None)
            else:
                setattr(parent, attr, value)


def request():
    profile = {"profile_id": "offline", "settings_sha256": "a" * 64}
    return {
        "schema_version": "1",
        "source": {"kind": "new", "prompt": "Create a tabletop scene"},
        "criteria": [{
            "criterion_id": "layout",
            "kind": "structural",
            "evidence_producer": "graph-check-v1",
            "requirement": "required",
            "evaluator_version": "1",
            "required_modalities": ["scene_graph"],
            "coordinate_frames": ["world"],
            "observation_window": {"start_step": 0, "end_step": 0},
            "rubric": "Objects must be present",
            "subjects": ["table"],
            "limit": {"operator": "ge", "value": 1.0, "unit": "count"},
        }],
        "preserved": [],
        "allowed_interventions": [],
        "execution": {
            "generation_model": {**profile, "billing": "free"},
            "assessment_model": {**profile, "billing": "free"},
            "runtime": profile,
            "database": profile,
            "policy": None,
            "capture": profile,
            "seed": 42,
            "timestep_seconds": 0.01,
            "decimation": 2,
            "dcrg": None,
        },
        "budget": {
            "max_candidates": 2,
            "max_revisions": 1,
            "max_runtime_seconds": 60.0,
            "max_model_calls": 0,
            "max_model_tokens": 0,
            "max_cost_usd": 0.0,
            "max_realizations": 0,
            "max_steps": 0,
            "max_observations": 0,
            "max_policy_episodes": 0,
            "max_policy_steps": 0,
            "per_operation_timeout_seconds": 10.0,
            "total_deadline_seconds": 60.0,
        },
        "effects": {
            "allow_paid_models": False,
            "allow_runtime": False,
            "allow_database_reads": False,
            "allow_publication": False,
        },
    }


PREFIX = "isaaclab_arena.agentic_environment_generation.workflow"
PRIVATE = "PRIVATE_DO_NOT_ECHO_82a72"


def cli():
    try:
        from isaaclab_arena.agentic_environment_generation.workflow import cli as entry

        return entry
    except ModuleNotFoundError:
        pytest.fail("read-only inspect-contract CLI is missing")


def test_shared_foreground_application_constructs_with_only_explicit_inert_adapters(monkeypatch):
    import builtins
    import importlib
    import importlib.abc
    import importlib.util
    import os
    import sys
    from types import SimpleNamespace

    forbidden = (
        "isaaclab_arena_examples", "sqlite3", "fastapi", "strawberry", "dotenv",
        "neo4j", "openai", "anthropic", "httpx", "requests", "torch", "isaacsim",
        "isaaclab", "omni", "pxr",
        "isaaclab_arena.agentic_environment_generation.workbench.journal",
        "isaaclab_arena.agentic_environment_generation.environment_generation_agent",
        "isaaclab_arena.agentic_environment_generation.inference_backend",
    )
    blocked, constructed = [], []
    original_import = builtins.__import__

    def check(name):
        if any(name == item or name.startswith(item + ".") for item in forbidden):
            blocked.append(name)
            raise AssertionError("cold application blocked dependency: " + name)

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        resolved = importlib.util.resolve_name("." * level + name, globals["__package__"]) if level else name
        check(resolved)
        return original_import(name, globals, locals, fromlist, level)

    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            check(fullname)

    class NoEffects:
        def __getattr__(self, name):
            raise AssertionError("cold application touched an external port: " + name)

        def __call__(self, *args, **kwargs):
            raise AssertionError("cold application constructed an execution adapter")

    ports = NoEffects()

    def no_ambient(name, default=None):
        if name in {"PYDANTIC_VALIDATE_CORE_SCHEMAS", "PYDANTIC_DISABLE_PLUGINS"}:
            return default
        return ports()

    def ownership_factory(area):
        constructed.append(area)
        return ports

    # Selected-module cold reload, not a pristine interpreter. Restore both
    # module identities and parent bindings so later real type checks stay valid.
    saved = {name: module for name, module in sys.modules.items()
             if name == PREFIX or name.startswith(PREFIX + ".")}
    parent = sys.modules[PREFIX.rpartition(".")[0]]
    previous = vars(parent).get("workflow")
    for name in saved:
        del sys.modules[name]
    if "workflow" in vars(parent):
        delattr(parent, "workflow")
    try:
        with monkeypatch.context() as guard:
            guard.setattr(builtins, "__import__", guarded)
            guard.setattr(sys, "meta_path", [Guard(), *sys.meta_path])
            guard.setattr(os, "getenv", no_ambient)
            guard.setattr(os, "environ", ports)
            assert importlib.util.find_spec(PREFIX + ".application") is not None, (
                "shared foreground application missing"
            )
            from isaaclab_arena.agentic_environment_generation.workflow.application import ForegroundWorkflow
            from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import ScenePortProfile
            from isaaclab_arena.agentic_environment_generation.workflow.scene_ports import ModelCeiling, ScenePorts
            from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

            reservation = dict(model_calls=1, model_tokens=1, cost_ceiling_usd=0, runtime_allowance_seconds=1)
            profile = ScenePortProfile(
                port_id="cold-synthetic", assurance="synthetic", owned_worker=True,
                producer_ids=("scene.visible",), observe=reservation, repair=reservation,
            )
            ceiling = ModelCeiling(
                max_calls=1, max_tokens=1, max_cost_usd="0", timeout_seconds=1,
                per_call_bound=dict(version=1, attested=True, model="literal", endpoint="literal",
                                    max_tokens=1, max_cost_usd="0"),
            )
            store, area = ports, object()
            authority = SimpleNamespace(store=store, protect_public=ports)
            kwargs = dict(
                store=store, authority=authority, gate=ports, private_parent="/not-opened",
                artifacts=SimpleNamespace(area=area), artifact_root="/not-opened",
                catalogue_sha256="a" * 64, generation_reservation=ports, prior_factory=ports,
                initial_worker_factory=ports, scene_worker_factory=ports, validate_document=ports,
                scene_options=dict(profile=profile, artifacts=ports, capture=ports,
                                   model_ceilings={role: ceiling for role in ("generation", "assessment")},
                                   capture_steps=1, capture_timeout_seconds=1, output_root="/not-opened",
                                   direct_root_subjects=(), displacement_tolerance_m=0.001),
                owner_lease_factory=ports, initial_receiver_factory=ports, scene_ports_factory=ports,
                recovery_factory=ports, ownership_artifacts_factory=ownership_factory, cancellation=ports,
            )
            app = ForegroundWorkflow(**kwargs)
            assert type(app.service) is WorkflowService and type(app._support) is ScenePorts
            assert app.service.bound_store is store and app.ownership is ports
            assert app._local == {} and app._recoveries == {} and app._cancel_controls == {}
            assert constructed == [area] and blocked == []
            for dependency in ("owner_lease_factory", "initial_receiver_factory", "scene_ports_factory",
                               "recovery_factory", "ownership_artifacts_factory", "cancellation"):
                with pytest.raises(TypeError, match=dependency):
                    ForegroundWorkflow(**{key: value for key, value in kwargs.items() if key != dependency})
            for change in (dict(owned_worker=False), dict(assurance="native-unverified")):
                with pytest.raises(ValueError, match="Only explicitly synthetic owned scene"):
                    ForegroundWorkflow(**(kwargs | {"scene_options": kwargs["scene_options"] | {
                        "profile": profile.model_copy(update=change)}}))
            assert constructed == [area] and blocked == []
    finally:
        for name in tuple(sys.modules):
            if name == PREFIX or name.startswith(PREFIX + "."):
                del sys.modules[name]
        sys.modules.update(saved)
        if previous is None:
            vars(parent).pop("workflow", None)
        else:
            parent.workflow = previous


def test_shared_foreground_extraction_preserves_operational_ast():
    import ast
    import inspect

    from isaaclab_arena.agentic_environment_generation.workflow import application

    source = inspect.getsource(application)
    tree = ast.parse(source)
    core = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    factories = {
        "_owner_lease_factory": "ForegroundOwnerLease",
        "_initial_receiver_factory": "InitialGenerationReceiver",
        "_scene_ports_factory": "ForegroundScenePorts",
        "_recovery_factory": "ForegroundGenerationRecovery",
    }
    helpers = {
        "cancel_workflow",
        "close_controls",
        "finish_cancelled",
        "start_owner_control",
        "stop_local",
        "stop_requested",
    }

    class OriginalCalls(ast.NodeTransformer):

        def visit_FunctionDef(self, node):
            if node.name in {"_generate", "_scene", "_scene_phase", "_drive_scene"}:
                assert node.args.kwonlyargs[-1].arg == "resume_receipt"
                assert ast.dump(node.args.kw_defaults[-1]) == "Constant(value=None)"
                node.args.kwonlyargs.pop()
                node.args.kw_defaults.pop()
            return self.generic_visit(node)

        def visit_If(self, node):
            if ast.unparse(node.test) == "resume_receipt is None":
                assert not node.orelse and len(node.body) == 1
                assert isinstance(node.body[0], ast.Expr)
                assert ast.unparse(node.body[0].value.func) == "self.service.start_scene"
                return node.body
            return self.generic_visit(node)

        def visit_IfExp(self, node):
            if ast.unparse(node.test) == "resume_receipt is None":
                assert ast.unparse(node.body) == "run.version"
                assert ast.unparse(node.orelse) == "resume_receipt.after_version"
                return node.body
            return self.generic_visit(node)

        def visit_Call(self, node):
            for kw in tuple(node.keywords):
                if kw.arg is None and isinstance(kw.value, ast.IfExp):
                    assert ast.unparse(kw.value) in {
                        "{} if resume_receipt is None else dict(resume_operation_id=resume_receipt.operation_id)",
                        "{} if resume_receipt is None else dict(resume_receipt=resume_receipt)",
                    }
                    node.keywords.remove(kw)
            self.generic_visit(node)
            call = node.func
            if isinstance(call, ast.Attribute):
                if isinstance(call.value, ast.Name) and call.value.id == "self" and call.attr in factories:
                    node.func = ast.Name(id=factories[call.attr], ctx=ast.Load())
                elif (
                    isinstance(call.value, ast.Attribute)
                    and call.value.attr == "_cancellation"
                    and isinstance(call.value.value, ast.Name)
                    and call.value.value.id == "self"
                    and call.attr in helpers
                ):
                    node.func = ast.Name(id=call.attr, ctx=ast.Load())
            return node

    # The additive keyed API is tested separately; every pre-existing operation
    # must still match the frozen extraction fingerprint without rebasing it.
    operations = [
        node
        for node in core.body
        if isinstance(node, ast.FunctionDef)
        and node.name
        not in {"__init__", "cancel_keyed", "resume_keyed", "_resume_pin", "_resume_result", "_resume_reconcile"}
    ]
    normalized = "\n".join(ast.dump(OriginalCalls().visit(node), include_attributes=False) for node in operations)
    # Captured from the original class with the sandbox's Python 3.12 AST.
    # Only enumerated adapter calls may differ; branch/order stays exact.
    assert (
        hashlib.sha256(normalized.encode()).hexdigest()
        == "bd37180f4ed0254fbde9ce98d4843579bb7400453d14e0a4886b59f52264d27f"
    )


def test_extracted_accounting_compatibility_exports_and_exact_bodies():
    import ast
    import inspect

    from isaaclab_arena.agentic_environment_generation.workflow import accounting, inference_transport

    expected = {
        "_usd_units": "3560ac2d98cfca8d846816310dc288b302143d5a6ef238a29c638825dc9f331d",
        "checked_workflow_accounting": "64dca39c621d528b4f94bc7c19b6a535abd536fc5514e89fd3a6f3f6362ad1e9",
        "CallAllowance": "31ad628a7e867f0a463b3ebdfb3ff775743820e8a78aab6e1c966bc3026c8b8d",
        "bounded_client": "26be3539cddde8e46a64dd858b1a35c2927f2f8e533d79385f049efe8e41daa5",
        "managed_inference_active": "186082ac2bf0422d0f15d8c00b5df30735b6a0fa5869224756a579d470938f14",
    }
    for name, digest in expected.items():
        obj = getattr(inference_transport, name)
        source = inspect.getsource(obj)
        # AST segment omits decorators consistently with the pre-extraction baseline.
        segment = ast.get_source_segment(source, ast.parse(source).body[0])
        assert hashlib.sha256(segment.encode()).hexdigest() == digest
    assert inference_transport._usd_units is accounting._usd_units
    assert inference_transport.checked_workflow_accounting is accounting.checked_workflow_accounting
    value = dict(version=1, attested=True, model="literal", endpoint="literal/", max_tokens=1, max_cost_usd="0.000000001")
    checked = accounting.checked_workflow_accounting(value, model="literal", endpoint="literal/")
    assert checked == value and checked is not value
    assert accounting._usd_units(value["max_cost_usd"]) == 1
    for change in ({"version": True}, {"attested": 1}, {"max_tokens": True}, {"max_tokens": 0},
                   {"max_cost_usd": "1e-9"}, {"max_cost_usd": 0}, {"extra": 1}):
        with pytest.raises(ValueError):
            accounting.checked_workflow_accounting(value | change)
    with pytest.raises(ValueError):
        accounting.checked_workflow_accounting(value, endpoint="literal")


def test_foreground_authority_cold_construction_has_no_web_or_effect_dependencies(monkeypatch):
    import builtins
    import importlib
    import importlib.abc
    import importlib.util
    import sys
    from types import SimpleNamespace

    example = "isaaclab_arena_examples.agentic_environment_generation"
    forbidden = (
        example + ".web_api",
        "sqlite3",
        "fastapi",
        "strawberry",
        "dotenv",
        "neo4j",
        "openai",
        "anthropic",
        "httpx",
        "requests",
        "torch",
        "isaacsim",
        "isaaclab",
        "omni",
        "pxr",
        "isaaclab_arena.agentic_environment_generation.workbench.journal",
        "isaaclab_arena.agentic_environment_generation.environment_generation_agent",
        "isaaclab_arena.agentic_environment_generation.inference_backend",
    )
    blocked, transport_imports = [], []
    original = builtins.__import__

    def check(name):
        if name == PREFIX + ".inference_transport":
            # Its import is pure today; record it so the legacy RED reaches the
            # eager web edge first, then require the direct accounting seam.
            transport_imports.append(name)
        if any(name == item or name.startswith(item + ".") for item in forbidden):
            blocked.append(name)
            raise AssertionError("cold authority blocked dependency: " + name)

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        resolved = importlib.util.resolve_name("." * level + name, globals["__package__"]) if level else name
        check(resolved)
        return original(name, globals, locals, fromlist, level)

    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            check(fullname)

    class NoPorts:
        def __getattr__(self, name):
            raise AssertionError("cold authority touched an external port")

        def __call__(self, *args, **kwargs):
            raise AssertionError("cold authority resolved a credential or principal")

    for name in tuple(sys.modules):
        if (
            name == example + ".foreground_authorization"
            or name == PREFIX
            or name.startswith(PREFIX + ".")
            or name == "isaaclab_arena.agentic_environment_generation.inference_profiles"
        ):
            parent_name, _, child = name.rpartition(".")
            parent = sys.modules.get(parent_name)
            if parent is not None:
                monkeypatch.delattr(parent, child, raising=False)
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(sys, "meta_path", [Guard(), *sys.meta_path])
    import os

    ports = NoPorts()

    def no_ambient(name, default=None):
        # Pydantic checks these noncredential runtime toggles while defining
        # models. Supply defaults without reading the actual environment.
        if name in {"PYDANTIC_VALIDATE_CORE_SCHEMAS", "PYDANTIC_DISABLE_PLUGINS"}:
            return default
        return ports()

    with monkeypatch.context() as ambient:
        ambient.setattr(os, "getenv", no_ambient)
        ambient.setattr(os, "environ", ports)
        # The local guard runs before the harness guard; no web code executes in RED.
        from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import (
            ForegroundAuthority,
            checked_workflow_accounting,
            model_settings_sha256,
        )
        from isaaclab_arena.agentic_environment_generation.workflow.accounting import (
            checked_workflow_accounting as pure_accounting,
        )

        assert checked_workflow_accounting is pure_accounting

        store = SimpleNamespace(database="db", scope={"deployment_id": "dep", "workspace_id": "workspace"})
        authority = ForegroundAuthority(
            database="db",
            deployment_id="dep",
            workspace_id="workspace",
            store=store,
            grants=ports,
            clock=ports,
            principal_lookup=ports,
            profiles={},
            current_config=ports,
        )
        assert authority.scope == dict(database="db", deployment_id="dep", workspace_id="workspace")
        assert (
            len(
                model_settings_sha256(
                    dict(api_key=PRIVATE, model="literal-model", base_url="https://api.openai.com/v1"), billing="free"
                )
            )
            == 64
        )
        authority.close()
        assert blocked == [] and transport_imports == []
        assert not any(
            name == item or name.startswith(item + ".")
            for name in sys.modules
            for item in (example + ".web_api", "sqlite3")
        )


def provider_config(**changes):
    return dict(api_key=PRIVATE, model="literal-model", base_url="https://api.openai.com/v1") | changes


def explicit_inference_profile():
    return {
        "id": "literal-policy",
        "revision": 1,
        "provider": "openai",
        "model": "literal-model",
        "endpoint": "https://api.openai.com/v1",
        "origin": "user_defined",
        "support": "unverified",
        "verification": "not_checked",
        "documentation_urls": [],
        "request_policy": {
            "api": "chat_completions",
            "temperature_mode": "omitted",
            "token_limit_parameter": "max_tokens",
            "structured_output": "json_object",
            "multimodal_output": "omitted",
            "store": False,
        },
    }


def test_provider_extraction_preserves_exact_bodies_constants_and_legacy_exports():
    import ast
    import inspect
    from pathlib import Path

    from isaaclab_arena.agentic_environment_generation.workflow import provider_configuration
    from isaaclab_arena_examples.agentic_environment_generation import foreground_authorization as authority

    expected = {
        "checked_config": "0bd761dffd10e519c811a9b24165b15e5438dfa338c454869dbb1321a81d90f5",
        "reject_secret": "77281c8b880ed8f5305aee4315c3ac7b00d495b06bcdd64d37eaa1bef6e76923",
        "bounded_client": "a083a47a0eef05358f8ab7ef4bfe1fb197f63b15ef6d66e7e3bf246f3bfaa3fa",
        "worker_environment": "f00f6dda3ea07a66a75d0b4c61a157d93c9d2d175ab3ef3e20aada7695fa43db",
        "_locked": "7eb332d5c8a621d2c3fbddee546bf39e245b3acd788fbdb9de6f988f37e05cdc",
        "_hash": "a362203e3eeb4079fd6eaf7c935be8342d7ceb8294caf823b5e8a3ec0ab87cce",
        "_config": "7a42caf4201f80952b5cd76c0e4952fb0154322371316cce37db78ca99c232e7",
        "model_settings_sha256": "1a68739a4bceebdfb625ef97aded911630014f91871fbcd445be1fe6339f98b7",
        "_deadline": "64d41471dca77797103a89257ec072a5aa429b76239816447d77494bdf2257a6",
        "ForegroundAuthority": "bbe55babe0f63f93c42aac967407d1da3bb3ed7f80190fba0d9499f4d150b9d5",
    }

    # Original class AST captured before keyed resume. Normalize only the
    # enumerated optional trusted-snapshot plumbing; all legacy bodies remain.
    class LegacyAuthority(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            if node.name in {"check_resume_eligibility", "apply_resume_authority"}:
                return None
            optional = {
                "_retained",
                "bind_workflow_models",
                "require_scene_execute",
                "bind_run",
                "renew_run",
                "require_execute",
            }
            if node.name in optional:
                assert node.args.kwonlyargs[-1].arg == "retained_run"
                assert ast.dump(node.args.kw_defaults[-1]) == "Constant(value=None)"
                node.args.kwonlyargs.pop()
                node.args.kw_defaults.pop()
            return self.generic_visit(node)

        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"_retained", "require_execute"}:
                node.keywords = [kw for kw in node.keywords if kw.arg != "retained_run"]
            return self.generic_visit(node)

        def visit_IfExp(self, node):
            if ast.unparse(node.test) == "retained_run is None":
                assert ast.unparse(node.body) == "self.store.get_run(run_id)"
                assert ast.unparse(node.orelse) == "retained_run"
                return node.body
            return self.generic_visit(node)

    legacy = Path(authority.__file__).parent / "web_api/provider_security.py"
    sources = [inspect.getsource(provider_configuration), inspect.getsource(authority), legacy.read_text()]
    actual = {}
    for source in sources:
        for node in ast.parse(source).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                assert node.name not in actual, "duplicate implementation"
                segment = (
                    ast.dump(LegacyAuthority().visit(node), include_attributes=False)
                    if node.name == "ForegroundAuthority"
                    else ast.get_source_segment(source, node)
                )
                actual[node.name] = hashlib.sha256(segment.encode()).hexdigest()
    assert actual == expected
    # Core isolation must not execute the eager legacy package just to inspect
    # its exports. A direct import binding preserves identity, not a wrapper.
    imports = [
        node
        for node in ast.parse(sources[-1]).body
        if isinstance(node, ast.ImportFrom) and node.module == PREFIX + ".provider_configuration"
    ]
    assert len(imports) == 1 and imports[0].level == 0
    assert {(item.name, item.asname) for item in imports[0].names} == {
        (name, None) for name in ("PROVIDERS", "ENDPOINTS", "checked_config", "reject_secret")
    }
    assert authority.checked_config is provider_configuration.checked_config
    assert authority.reject_secret is provider_configuration.reject_secret

    assert provider_configuration.PROVIDERS == (
        {"id": "openai", "label": "OpenAI", "base_url": "https://api.openai.com/v1"},
        {
            "id": "gemini",
            "label": "Google Gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        },
        {"id": "openrouter", "label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1"},
        {"id": "nvidia", "label": "NVIDIA", "base_url": "https://integrate.api.nvidia.com/v1"},
    )
    assert provider_configuration.ENDPOINTS == {p["id"]: p["base_url"] for p in provider_configuration.PROVIDERS}


def test_provider_configuration_preserves_literal_endpoints_and_trusted_server_policy():
    from isaaclab_arena.agentic_environment_generation.workflow.provider_configuration import ENDPOINTS, checked_config

    for endpoint in ENDPOINTS.values():
        config = provider_config(base_url=endpoint)
        checked = checked_config(config | {"ignored": PRIVATE})
        assert checked == config and checked is not config
    for endpoint in ("http://localhost:9999/v1/", "https://api.openai.com/v1/", "HTTPS://example.invalid/V1"):
        config = provider_config(api_key="Z", base_url=endpoint)
        assert checked_config(config, trusted_server=True) == config
        with pytest.raises(ValueError, match="^Invalid provider configuration$"):
            checked_config(config)
    assert checked_config(provider_config(api_key="x" * 4096, model="y" * 256))
    assert checked_config(provider_config(api_key="x" * 16))


@pytest.mark.parametrize(
    "change,trusted",
    [
        ({"api_key": ""}, True),
        ({"api_key": "x" * 15}, False),
        ({"api_key": "x" * 4097}, True),
        ({"api_key": None}, True),
        ({"api_key": PRIVATE + " "}, True),
        ({"model": ""}, False),
        ({"model": "m" * 257}, True),
        ({"model": "has space"}, True),
        ({"model": "non-ascii-\u00e9"}, True),
        ({"model": 7}, True),
        ({"base_url": None}, True),
        ({"base_url": "ftp://example.invalid"}, True),
        ({"base_url": "http:///missing-host"}, True),
        ({"base_url": "https://example.invalid/has space"}, True),
        ({"base_url": "https://api.openai.com/v1/"}, False),
    ],
)
def test_provider_configuration_rejects_invalid_inputs_with_static_errors(change, trusted):
    from isaaclab_arena.agentic_environment_generation.workflow.provider_configuration import checked_config

    with pytest.raises(ValueError, match="^Invalid provider configuration$"):
        checked_config(provider_config(**change), trusted_server=trusted)
    with pytest.raises(ValueError, match="^Invalid provider configuration$"):
        checked_config(None)


def test_provider_profile_validation_detaches_and_preserves_request_policy_errors():
    from isaaclab_arena.agentic_environment_generation.workflow.provider_configuration import checked_config

    profile = explicit_inference_profile()
    checked = checked_config(provider_config(inference_profile=profile))
    assert checked["inference_profile"] == profile
    assert checked["inference_profile"] is not profile
    assert checked["inference_profile"]["request_policy"] is not profile["request_policy"]
    for change, message in (
        ({"model": "other"}, "Inference profile model mismatch"),
        (
            {"provider": "nvidia", "endpoint": "https://integrate.api.nvidia.com/v1"},
            "Inference profile endpoint mismatch",
        ),
        ({"extra": True}, "Invalid inference profile"),
        ({"request_policy": profile["request_policy"] | {"store": True}}, "Invalid request policy"),
        ({"request_policy": profile["request_policy"] | {"extra": False}}, "Invalid request policy"),
    ):
        with pytest.raises(ValueError, match="^" + message + "$"):
            checked_config(provider_config(inference_profile=profile | change))
    # Profile endpoint tolerance is not provider endpoint normalization.
    assert checked_config(
        provider_config(base_url="https://api.openai.com/v1/", inference_profile=profile), trusted_server=True
    )["base_url"].endswith("/")


@pytest.mark.parametrize("value", [PRIVATE, "prefix-" + PRIVATE, {PRIVATE: 0}, {"safe": [0, (PRIVATE,)]}])
def test_provider_secret_screen_is_recursive_and_errors_are_static(value):
    from isaaclab_arena.agentic_environment_generation.workflow.provider_configuration import reject_secret

    with pytest.raises(ValueError, match="^Protected credential material in generation data$"):
        reject_secret(value, PRIVATE)
    assert reject_secret(value, "") is None
    assert reject_secret({"safe": [0, None, ("public",)]}, PRIVATE) is None
    # Preserve the existing scope: sets and bytes are not recursively screened.
    assert reject_secret({PRIVATE}, PRIVATE) is None
    assert reject_secret(PRIVATE.encode(), PRIVATE) is None


@pytest.mark.parametrize(
    "change,trusted",
    [
        ({"model": PRIVATE}, False),
        ({"base_url": "https://example.invalid/" + PRIVATE}, True),
        ({"api_key": "OpenAI"}, True),
        ({"api_key": "credential_ref"}, True),
        ({"inference_profile": explicit_inference_profile() | {"id": PRIVATE}}, False),
    ],
)
def test_provider_configuration_screens_public_literals_and_profiles(change, trusted):
    from isaaclab_arena.agentic_environment_generation.workflow.provider_configuration import checked_config

    with pytest.raises(ValueError, match="^Protected credential material in generation data$"):
        checked_config(provider_config(**change), trusted_server=trusted)


def resume_authority_fixture():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json, parse_contract
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import (
        ForegroundAuthority,
        model_settings_sha256,
    )

    records, calls = {}, []
    now = [100.0]
    config = provider_config()
    profile = dict(profile_id="offline", billing="free", settings_sha256=model_settings_sha256(config, billing="free"))
    raw = request()
    raw["execution"]["generation_model"] = raw["execution"]["assessment_model"] = profile
    raw["effects"]["allow_operational_writes"] = True
    contract = parse_contract(json.dumps(raw))
    run = SimpleNamespace(run_id="run", operation_id="original-submit", contract_json=canonical_json(contract))
    scope = dict(database="db", deployment_id="dep", workspace_id="workspace")

    class Grants:
        def issue(self, principal, binding, kind, profile, value, expires):
            reference = "grant-" + str(len(calls))
            calls.append(("issue", binding))
            records[reference] = (principal, binding, kind, value, expires)
            return {"grant_id": reference}

        def resolve(self, principal, reference, binding, kind):
            p, b, k, value, expires = records[reference]
            if (p, b, k) != (principal, binding, kind) or now[0] >= expires:
                raise ValueError("expired")
            return value

        def revoke(self, reference):
            calls.append(("revoke", reference))
            records.pop(reference, None)

        def protect_public(self, value):
            pass

    def no_database(*args):
        pytest.fail("resume authority must use the already checked retained run, not DB under its guard")

    authority = ForegroundAuthority(
        **scope,
        store=SimpleNamespace(
            database="db", scope={k: v for k, v in scope.items() if k != "database"}, get_run=no_database
        ),
        grants=Grants(),
        clock=lambda: now[0],
        principal_lookup=lambda p: dict(scope, principal=p, expires_at=1000, revoked=False),
        profiles={"offline": profile},
        current_config=lambda p: dict(config=config, expires_at=900),
    )
    return SimpleNamespace(authority=authority, contract=contract, run=run, calls=calls, now=now)


def keyed_resume_fixture():
    from contextlib import contextmanager
    from threading import RLock
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.application import ForegroundWorkflow
    from isaaclab_arena.agentic_environment_generation.workflow.commands import (
        ResumeAdmission,
        ResumeSelection,
        command_digest,
        command_json,
        make_resume_receipt,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.tests.test_environment_workflow_service import contract, coordinator_fixture

    f = coordinator_fixture()
    app = ForegroundWorkflow.__new__(ForegroundWorkflow)
    app.store, app.authority, app.gate = f.store, f.coordinator._authority, f.coordinator._gate
    import time

    app.gate._clock = time.monotonic  # New real coordinator captures this process's clock.
    app._closed, app._lock = False, RLock()
    app._local, app._recoveries, app._cancel_controls = {}, {}, {}
    app._resume_deliveries, app._resume_busy = {}, set()
    app._owner_control = False
    app._admission_listener = None
    state = SimpleNamespace(
        receipt=None,
        version=1,
        in_guard=False,
        fail_apply=False,
        stop=False,
        admission_error=False,
        screen_error=False,
        reentry=None,
        claim_key=None,
    )
    request = contract()
    run = f.store.get_run("run")
    run.operation_id = "original-submit"
    reservation = dict(model_calls=2, model_tokens=100, cost_ceiling_usd=0, runtime_allowance_seconds=5)
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import GenerationReservation

    reservation = GenerationReservation(**reservation)
    selection = ResumeSelection(
        run_id="run", version=1, contract_digest=contract_digest(request), branch="generation", intent_id="intent"
    )

    def current_run(run_id):
        assert not state.in_guard, "DB access under authority guard"
        run.version = state.version
        return run

    def preview(run_id):
        return SimpleNamespace(
            run=current_run(run_id), selection=selection.model_copy(update={"version": state.version})
        )

    def admit(key, payload, *, selection, eligibility, protect):
        assert eligibility == "current" and not state.in_guard
        f.calls.append("admit_commit")
        text = command_json(payload)
        state.receipt = make_resume_receipt(
            scope=dict(database="neo4j", deployment_id="dep", workspace_id="ws"),
            operation_id=key,
            run_id="run",
            payload_json=text,
            payload_digest=command_digest(text),
            before_version=1,
            after_version=2,
            contract_digest=selection.contract_digest,
            selection=selection.model_dump(mode="json"),
            disposition="continuation_admitted",
            reason=None,
            authorization_action="none",
            events=[dict(sequence=2, kind="ResumeAdmitted", source_id=selection.intent_id)],
        )
        state.version = 2
        if state.admission_error:
            raise OSError("private commit uncertainty")
        return ResumeAdmission(fresh=True, receipt=state.receipt)

    @contextmanager
    def guard():
        assert not state.in_guard
        state.in_guard = True
        try:
            yield
        finally:
            state.in_guard = False

    def apply(principal, contract, *, run, action, catalogue_sha256):
        assert state.in_guard and "admit_screen" in f.calls and action == "none"
        f.calls.append("apply")
        if state.reentry:
            state.reentry()
        if state.fail_apply:
            raise ValueError("private apply failed")

    def protect(value):
        if isinstance(value, dict) and value.get("fresh") is True:
            f.calls.append("admit_screen")
            if state.screen_error:
                raise PermissionError("private screen failed")

    def claim(intent, owner, epoch, *, resume_operation_id=None):
        assert not state.in_guard
        assert (intent, resume_operation_id, state.version) == ("intent", "resume-key", 2)
        state.claim_key = resume_operation_id
        f.calls.append("claim")
        return f.prepared.registration.fence

    f.store.get_run, f.store.preview_resume = current_run, preview

    def get_resume_receipt(key):
        assert not state.in_guard, "DB receipt lookup under authority guard"
        return state.receipt if state.receipt is not None and key == state.receipt.operation_id else None

    f.store.get_resume_receipt = get_resume_receipt
    f.store.admit_resume, f.store.claim_intent = admit, claim
    f.store.pending_generation = lambda run: dict(intent_id="intent", reservation=reservation)
    f.store.get_owner = lambda: None
    app.authority.protect_public = protect
    app.authority.mutation_guard = guard
    app.authority.check_resume_eligibility = lambda *a, **kw: "current"
    app.authority.apply_resume_authority = apply
    app._preflight = lambda *a: f.calls.append("preflight")
    app._ready = lambda *a: f.calls.append("ready")
    app.service = WorkflowService(f.store, app.authority, app.gate, validate_support=None)
    app._cancellation = SimpleNamespace(stop_requested=lambda *a: state.stop)
    app.private_parent, app.artifact_root, app.catalogue_sha256 = "/inert", "/inert", "a" * 64
    app.artifacts, app.ownership = SimpleNamespace(area=None), None
    app.prior_factory = lambda **kw: None
    app.initial_worker_factory = lambda **kw: f.worker
    app._owner_lease_factory = lambda *a, **kw: f.coordinator._lease
    f.worker.cleanup_verified = lambda *a: True
    app._initial_receiver_factory = lambda *a, **kw: SimpleNamespace(
        receive=lambda *a, **kw: SimpleNamespace(disposition="reconciliation_required")
    )
    app.validate_document = lambda *a: None
    app.generation_reservation = reservation
    app.status = lambda *a: dict(disposition="blocked", state="running")
    app._settle_cancel = lambda *a: None
    payload = dict(runId="run", expectedVersion=1, renewAuthorization=False)
    return SimpleNamespace(app=app, f=f, state=state, payload=payload)


@pytest.mark.parametrize("key", ["resume-key", "other-key"])
@pytest.mark.parametrize("callback_failure", [False, True])
def test_keyed_resume_guarded_reentry_precedes_receipt_lookup(key, callback_failure):
    t = keyed_resume_fixture()
    errors = []

    def reenter():
        try:
            t.app.resume_keyed("creator", key, t.payload, check_resume=None)
        except Exception as exc:
            errors.append(exc)
        if callback_failure:
            raise ValueError("private callback failure")

    t.state.reentry = reenter
    result = t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=lambda *a: None)
    assert len(errors) == 1
    assert type(errors[0]) is RuntimeError and str(errors[0]) == "Guarded resume reentry unavailable", repr(errors)
    assert result.execution == ("blocked" if callback_failure else "returned")
    assert t.f.calls.count("apply") == 1
    assert t.f.calls.count("send") == (0 if callback_failure else 1)
    assert not t.app._resume_busy and not t.state.in_guard
    before = list(t.f.calls)
    replay = t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=None)
    assert replay.receipt == result.receipt and replay.execution == "not_requested"
    assert t.f.calls[len(before) :] == ["read_auth"]


def test_keyed_resume_guarded_reentry_cannot_invert_cancel_control_lock():
    from contextlib import contextmanager
    from threading import Event, Lock, RLock, Thread

    t = keyed_resume_fixture()
    authority_lock, control_lock = RLock(), Lock()
    control_held, cancel_done = Event(), Event()
    errors, receipt_under_guard = [], []
    original_guard = t.app.authority.mutation_guard
    original_get = t.app.store.get_resume_receipt

    @contextmanager
    def guard():
        with authority_lock, original_guard():
            yield

    def get_receipt(key):
        if t.state.in_guard:
            receipt_under_guard.append(key)
        acquired = control_lock.acquire(timeout=1)
        assert acquired, "guarded receipt lookup waited on cancel control lock"
        try:
            return original_get(key)
        finally:
            control_lock.release()

    def cancel_screen():
        with control_lock:
            control_held.set()
            with authority_lock:
                cancel_done.set()

    cancel = Thread(target=cancel_screen)

    def reenter():
        cancel.start()
        assert control_held.wait(2), "cancel did not reach control barrier"
        try:
            t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=None)
        except Exception as exc:
            errors.append(exc)

    t.app.authority.mutation_guard = guard
    t.app.store.get_resume_receipt = get_receipt
    t.state.reentry = reenter
    try:
        result = t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=lambda *a: None)
    finally:
        if cancel.ident is not None:
            cancel.join(3)
    assert not cancel.is_alive() and cancel_done.is_set()
    assert receipt_under_guard == [], "DB entered while callback held authority and cancel held control"
    assert len(errors) == 1 and type(errors[0]) is RuntimeError
    assert result.execution == "returned" and t.f.calls.count("send") == 1


def test_keyed_resume_concurrent_authorized_replay_is_not_reentry():
    from threading import Thread

    t = keyed_resume_fixture()
    results, errors = [], []
    # This thread-safe retained read is deliberately independent of the private
    # guard. The single-thread fixture's global in_guard flag cannot model it.
    t.app.store.get_resume_receipt = lambda key: t.state.receipt

    def replay():
        try:
            results.append(t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=None))
        except Exception as exc:
            errors.append(exc)

    def reenter():
        thread = Thread(target=replay)
        thread.start()
        thread.join(2)
        assert not thread.is_alive(), "ordinary replay serialized behind private delivery"

    t.state.reentry = reenter
    result = t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=lambda *a: None)
    assert not errors and len(results) == 1
    assert results[0].execution == "not_requested" and results[0].receipt == result.receipt
    assert result.execution == "returned" and t.f.calls.count("send") == 1


def test_keyed_resume_fresh_generation_uses_existing_coordinator_once():
    from isaaclab_arena.agentic_environment_generation.workflow.application import ForegroundWorkflow

    assert callable(getattr(ForegroundWorkflow, "resume_keyed", None)), "acknowledged-fresh handler missing"
    t = keyed_resume_fixture()

    def permission(*a):
        t.f.calls.append("resume_permission")

    result = t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=permission)
    assert result.receipt == t.state.receipt and result.execution == "returned"
    assert t.f.calls.count("apply") == t.f.calls.count("prepare") == t.f.calls.count("send") == 1
    assert t.f.calls.index("admit_screen") < t.f.calls.index("apply") < t.f.calls.index("claim")
    assert t.state.claim_key == "resume-key" and "reserve" not in t.f.calls
    before = list(t.f.calls)
    replay = t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=None)
    assert replay.receipt == result.receipt and replay.execution == "not_requested"
    assert t.f.calls[len(before) :] == ["read_auth"]


@pytest.mark.parametrize(
    "fault", ["apply", "reentry", "commit", "screen", "stale", "pending_changed", "busy", "stop", "status"]
)
def test_keyed_resume_generation_failure_consumes_delivery_without_retry(fault):
    from isaaclab_arena.agentic_environment_generation.workflow.application import ForegroundWorkflow

    assert callable(getattr(ForegroundWorkflow, "resume_keyed", None)), "acknowledged-fresh handler missing"
    t = keyed_resume_fixture()
    if fault == "apply":
        t.state.fail_apply = True
    elif fault == "commit":
        t.state.admission_error = True
    elif fault == "screen":
        t.state.screen_error = True
    elif fault == "stop":
        t.state.stop = True
    elif fault == "pending_changed":
        original_pending = t.app.store.pending_generation

        def changed(run_id):
            result = original_pending(run_id)
            t.state.version = 3
            return result

        t.app.store.pending_generation = changed
    elif fault == "busy":
        from types import SimpleNamespace

        t.app._local["run"] = SimpleNamespace(busy=True)
    elif fault == "stale":
        original = t.app.authority.protect_public

        def screen(value):
            original(value)
            if isinstance(value, dict) and value.get("fresh") is True:
                t.state.version = 3

        t.app.authority.protect_public = screen
    elif fault == "status":

        def unavailable(*a):
            raise ValueError("private status failed")

        t.app.status = unavailable
    else:
        t.state.reentry = lambda: t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=None)
    if fault in {"commit", "screen"}:
        with pytest.raises((OSError, PermissionError)):
            t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=lambda *a: None)
    else:
        result = t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=lambda *a: None)
        assert result.receipt == t.state.receipt
        if fault == "status":
            assert result.status is None and result.status_status == "unavailable"
    if fault == "stale":
        assert t.app._cancel_controls == {}, "stale acknowledged pin cannot create owner control"
    if fault not in {"reentry", "status"}:
        assert "prepare" not in t.f.calls and "send" not in t.f.calls
    assert t.f.calls.count("apply") == (1 if fault in {"apply", "reentry", "status"} else 0)
    before = list(t.f.calls)
    replay = t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=None)
    assert replay.receipt == t.state.receipt and replay.execution == "not_requested"
    assert t.f.calls[len(before) :] == ["read_auth"]


@pytest.mark.parametrize("retained_local", [False, True])
def test_keyed_resume_scene_handoff_preserves_first_pin_and_does_not_start_scene(retained_local):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.commands import ResumeAdmission, make_resume_receipt
    from isaaclab_arena.tests.test_environment_workflow_service import keyed_scene_fixture

    t, scene = keyed_resume_fixture(), keyed_scene_fixture()
    original_preview, original_admit = t.app.store.preview_resume, t.app.store.admit_resume
    original_preview("run").run.state = "running"

    def preview(run_id):
        result = original_preview(run_id)
        result.selection = result.selection.model_copy(update={"branch": "scene", "intent_id": "a" * 64})
        return result

    def admit(*args, **kwargs):
        result = original_admit(*args, **kwargs)
        body = result.receipt.model_dump(
            mode="json", exclude={"receipt_digest", "kind", "codec_version", "receipt_version", "digest_codec"}
        )
        body["operation_id"] = "scene-resume"
        t.state.receipt = make_resume_receipt(**body)
        return ResumeAdmission(fresh=True, receipt=t.state.receipt)

    scene.store.preview_resume = preview
    scene.store.admit_resume = admit
    scene.store.get_resume_receipt = t.app.store.get_resume_receipt
    scene.store.result_records = lambda run: {}
    scene.store.start_scene = lambda *a, **kw: pytest.fail("keyed scene must not start or reserve new work")
    t.app.store, t.app.service = scene.store, scene.service
    scene.service._authority = t.app.authority
    scene.store.get_run = lambda run: original_preview(run).run
    scene.ports.restore_observations = lambda *a: None
    scene.ports.retire_terminal = lambda: None
    t.app.scene_options = {"profile": scene.ports.profile}
    t.app.scene_worker_factory = lambda **kw: t.f.worker
    t.app._scene_ports_factory = lambda **kw: scene.ports
    t.f.coordinator._lease.recover_unprepared_owner = lambda *a: None
    if retained_local:
        t.app._local["run"] = SimpleNamespace(busy=False, retired=False, stopped=False, ports=scene.ports)
    result = t.app.resume_keyed("creator", "scene-resume", t.payload, check_resume=lambda *a: None)
    assert result.receipt.selection.branch == "scene"
    assert scene.claims == [("a" * 64, "scene-resume"), ("b" * 64, None)]
    assert t.f.calls.count("apply") == 1
    assert result.execution == "returned"


@pytest.mark.parametrize("mode", ["fresh", "local", "local_error", "mismatched_local", "stale"])
def test_keyed_reconciliation_handoff_exact_fence_no_authority_or_autoscene(mode):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.commands import (
        ResumeAdmission,
        command_digest,
        command_json,
        make_resume_receipt,
    )

    t = keyed_resume_fixture()
    app, state, calls = t.app, t.state, t.f.calls
    fence, registration = t.f.prepared.registration.fence, t.f.prepared.registration
    original_preview = app.store.preview_resume

    def preview(run_id):
        result = original_preview(run_id)
        result.selection = result.selection.model_copy(update={"branch": "reconciliation", "fence": fence})
        return result

    def admit(key, payload, *, selection, eligibility, protect):
        assert eligibility is None
        text = command_json(payload)
        state.receipt = make_resume_receipt(
            scope=dict(database="neo4j", deployment_id="dep", workspace_id="ws"),
            operation_id=key,
            run_id="run",
            payload_json=text,
            payload_digest=command_digest(text),
            before_version=1,
            after_version=2,
            contract_digest=selection.contract_digest,
            selection=selection.model_dump(mode="json"),
            disposition="reconciliation_admitted",
            reason=None,
            authorization_action=None,
            events=[dict(sequence=2, kind="ResumeAdmitted", source_id="intent")],
        )
        state.version = 3 if mode == "stale" else 2
        return ResumeAdmission(fresh=True, receipt=state.receipt)

    def forbidden(*a, **kw):
        pytest.fail("reconciliation cannot bind, renew, probe, generate or autoscene")

    app.store.preview_resume, app.store.admit_resume = preview, admit
    app._preflight = app._ready = app._generate = app._scene = forbidden
    app.authority.check_resume_eligibility = app.authority.apply_resume_authority = forbidden
    app.authority.mutation_guard = forbidden
    pins = []
    attempt = SimpleNamespace(
        fence=fence,
        registration=registration,
        authorization=SimpleNamespace(principal="creator"),
        contract_json=original_preview("run").run.contract_json,
    )

    def exact(pin):
        pins.append(pin)
        assert pin == fence
        return attempt

    app.store.get_attempt = exact
    app.store.get_generation_attempt = forbidden

    def recovered(*args, **kwargs):
        calls.append("recover")
        if mode == "fresh":
            assert kwargs == dict(release_lease=True, resume_receipt=state.receipt)
        else:
            assert app._local["run"].busy is True
            if mode == "local_error":
                raise RuntimeError("private receiver failure")
        return SimpleNamespace(disposition="validation", attempt=attempt, run=original_preview("run").run)

    app._recovery_factory = lambda *a, **kw: SimpleNamespace(recover=recovered)
    app._settle_cancel = lambda *a: calls.append("settle")
    if mode in {"local", "local_error", "mismatched_local"}:
        prepared = t.f.prepared
        if mode == "mismatched_local":
            prepared = SimpleNamespace(registration=registration.model_copy(update={"registration_id": "other"}))
        app._local["run"] = SimpleNamespace(
            busy=False,
            retired=False,
            receiver=SimpleNamespace(receive=recovered),
            handle=SimpleNamespace(fence=fence, prepared=prepared),
        )
    result = app.resume_keyed("creator", "resume-key", t.payload, check_resume=lambda *a: None)
    assert result.receipt == state.receipt
    assert calls.count("recover") == (1 if mode in {"fresh", "local", "local_error"} else 0)
    assert (result.execution == "returned") == (mode in {"fresh", "local"})
    if mode in {"local", "local_error"}:
        assert app._local["run"].busy is False and calls.count("settle") == 1
    assert "apply" not in calls and "prepare" not in calls
    if mode != "stale":
        assert pins and all(pin == fence for pin in pins)


@pytest.mark.parametrize("failure", ["preflight", "readiness"])
def test_keyed_resume_check_only_unavailable_retains_refusal(failure):
    from isaaclab_arena.agentic_environment_generation.workflow.commands import (
        ResumeAdmission,
        command_digest,
        command_json,
        make_resume_receipt,
    )

    t = keyed_resume_fixture()

    def unavailable(*args):
        raise ValueError("private unavailable")

    setattr(t.app, "_preflight" if failure == "preflight" else "_ready", unavailable)

    def refuse(key, payload, *, selection, eligibility, protect):
        assert eligibility == "not_ready"
        text = command_json(payload)
        t.state.receipt = make_resume_receipt(
            scope=dict(database="neo4j", deployment_id="dep", workspace_id="ws"),
            operation_id=key,
            run_id="run",
            payload_json=text,
            payload_digest=command_digest(text),
            before_version=1,
            after_version=1,
            selection=selection.model_dump(mode="json"),
            contract_digest=selection.contract_digest,
            disposition="refused",
            reason="private_eligibility_not_ready",
            authorization_action=None,
            events=[],
        )
        return ResumeAdmission(fresh=True, receipt=t.state.receipt)

    t.app.store.admit_resume = refuse
    result = t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=lambda *a: None)
    assert result.execution == "not_requested" and result.receipt.disposition == "refused"
    assert "apply" not in t.f.calls and "prepare" not in t.f.calls
    before = list(t.f.calls)
    # Replay cannot even resolve newly missing mutable callback attributes.
    del t.app.authority.check_resume_eligibility
    del t.app.authority.apply_resume_authority
    assert t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=None).receipt == result.receipt
    assert t.f.calls[len(before) :] == ["read_auth"]


@pytest.mark.parametrize("failed_apply", [False, True])
def test_private_delivery_latch_rejects_repeated_fresh_transport_result(failed_apply):
    from isaaclab_arena.agentic_environment_generation.workflow.commands import ResumeAdmission

    t = keyed_resume_fixture()
    t.state.fail_apply = failed_apply
    first = t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=lambda *a: None)
    # An internal duplicate delivery is not a second capability. No public API
    # accepts this receipt/fresh value; inject only at the trusted service seam.
    t.app.service.admit_resume = lambda *a, **kw: ResumeAdmission(fresh=True, receipt=first.receipt)
    before = list(t.f.calls)
    result = t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=None)
    assert result.execution == "blocked" and result.receipt == first.receipt
    assert t.f.calls == before and t.f.calls.count("apply") == 1


@pytest.mark.parametrize("screen", ["status", "mutate", "receipt"])
def test_resume_known_receipt_survives_optional_screen_but_not_receipt_denial(screen):
    t = keyed_resume_fixture()
    original = t.app.authority.protect_public
    screened = []

    def protect(value):
        original(value)
        screened.append(value)
        if "receipt_digest" in value and screen == "receipt":
            raise PermissionError("receipt denied")
        if value.get("status_status") == "available":
            if screen == "status":
                raise PermissionError("private status sentinel")
            if screen == "mutate":
                value["status"]["state"] = "private mutation sentinel"

    t.app.authority.protect_public = protect
    if screen == "receipt":
        with pytest.raises(PermissionError, match="receipt denied"):
            t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=lambda *a: None)
        assert "apply" not in t.f.calls and "prepare" not in t.f.calls
    else:
        result = t.app.resume_keyed("creator", "resume-key", t.payload, check_resume=lambda *a: None)
        assert result.receipt == t.state.receipt and result.status is None and result.status_status == "unavailable"
        assert screened[-1] == result.model_dump(mode="json")
        assert "sentinel" not in result.model_dump_json()


@pytest.mark.parametrize("action", ["bind", "renew", "partial_bind"])
def test_keyed_handler_real_authority_applies_receipted_action_only_after_ack(action):
    from isaaclab_arena.agentic_environment_generation.workflow.commands import (
        ResumeAdmission,
        command_digest,
        command_json,
        make_resume_receipt,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json, contract_digest

    t, private = keyed_resume_fixture(), resume_authority_fixture()
    authority = private.authority
    if action == "renew":
        authority.apply_resume_authority(
            "creator", private.contract, run=private.run, action="bind", catalogue_sha256="a" * 64
        )
        private.now[0] = 300
    before = len(private.calls)
    original_run = t.app.store.get_run("run")
    original_run.contract_json = canonical_json(private.contract)
    original_preview = t.app.store.preview_resume

    def preview(run_id):
        value = original_preview(run_id)
        value.selection = value.selection.model_copy(update={"contract_digest": contract_digest(private.contract)})
        return value

    authority.store = t.app.store
    t.app.store.database = "db"
    t.app.store.scope = dict(deployment_id="dep", workspace_id="workspace")
    t.app.store.preview_resume = preview
    t.app.authority = t.app.service._authority = authority
    original_protect = t.f.coordinator._authority.protect_public
    authority.protect_public = original_protect
    expected = "bind" if action == "partial_bind" else action

    def admit(key, payload, *, selection, eligibility, protect):
        assert eligibility == expected and len(private.calls) == before
        text = command_json(payload)
        t.state.receipt = make_resume_receipt(
            scope=authority.scope,
            operation_id=key,
            run_id="run",
            payload_json=text,
            payload_digest=command_digest(text),
            before_version=1,
            after_version=2,
            selection=selection.model_dump(mode="json"),
            contract_digest=selection.contract_digest,
            disposition="continuation_admitted",
            reason=None,
            authorization_action=expected,
            events=[dict(sequence=2, kind="ResumeAdmitted", source_id="intent")],
        )
        t.state.version = 2
        return ResumeAdmission(fresh=True, receipt=t.state.receipt)

    t.app.store.admit_resume = admit
    issue = authority.grants.issue

    def acknowledged_issue(*a):
        assert "admit_screen" in t.f.calls and t.state.receipt.authorization_action == expected
        return issue(*a)

    authority.grants.issue = acknowledged_issue
    if action == "partial_bind":

        def fail_roles(*a, **kw):
            raise ValueError("private partial binding")

        authority.bind_workflow_models = fail_roles
    apply = authority.apply_resume_authority

    def apply_once(*a, **kw):
        assert authority._lock._is_owned()
        try:
            return apply(*a, **kw)
        finally:
            t.state.stop = True  # Never construct a worker in this grant-only slice.

    authority.apply_resume_authority = apply_once
    payload = t.payload | {"renewAuthorization": True}
    result = t.app.resume_keyed("creator", "resume-key", payload, check_resume=lambda *a: None)
    assert result.receipt.authorization_action == expected
    assert len([call for call in private.calls[before:] if call[0] == "issue"]) == 1
    assert authority._bindings["run"][0].principal == "creator"
    assert ("run" in authority._workflow_bindings) == (action != "partial_bind")
    issued = list(private.calls)
    authority.current_config = lambda *a: pytest.fail("replay must not resolve private configuration")
    replay = t.app.resume_keyed("creator", "resume-key", payload, check_resume=None)
    assert replay.receipt == result.receipt and replay.execution == "not_requested" and private.calls == issued
    assert "prepare" not in t.f.calls and "send" not in t.f.calls


def test_resume_authority_check_only_and_exact_bind_current_renew():
    f = resume_authority_fixture()
    authority, contract, run = f.authority, f.contract, f.run
    assert callable(getattr(authority, "check_resume_eligibility", None)), "pure resume eligibility missing"

    def check(renew):
        return authority.check_resume_eligibility("creator", contract, run=run, renew_authorization=renew)

    assert check(False) == "not_ready" and check(True) == "bind"
    assert f.calls == [] and authority._bindings == {}
    authority.apply_resume_authority("creator", contract, run=run, action="bind", catalogue_sha256="a" * 64)
    first = authority._bindings["run"][0]
    assert check(False) == "current" and check(True) == "renew"
    issued = list(f.calls)
    authority.apply_resume_authority("creator", contract, run=run, action="none", catalogue_sha256="a" * 64)
    assert f.calls == issued
    with pytest.raises(ValueError, match="Resume authority action changed"):
        authority.apply_resume_authority("creator", contract, run=run, action="bind", catalogue_sha256="a" * 64)
    assert f.calls == issued
    f.now[0] = 300
    assert check(False) == "not_ready" and check(True) == "renew"
    authority.apply_resume_authority("creator", contract, run=run, action="renew", catalogue_sha256="a" * 64)
    assert authority._bindings["run"][0] != first and check(False) == "current"
    authority._workflow_bindings.pop("run")
    assert check(False) == check(True) == "not_ready", "partial bindings must not be repaired implicitly"


def test_foreground_private_configuration_and_key_independent_hash_compatibility():
    from isaaclab_arena.agentic_environment_generation.inference_profiles import (
        frozen_builtin_profile,
        resolve_inference_profile,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import (
        PublicModelSettings,
        public_model_settings_sha256,
    )
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import (
        _config,
        model_settings_sha256,
    )

    profile = explicit_inference_profile()
    accounting = dict(
        version=1,
        attested=True,
        model="literal-model",
        endpoint="https://api.openai.com/v1",
        max_tokens=700,
        max_cost_usd="0.000000001",
    )
    for config, policy in (
        (provider_config(), None),
        (
            provider_config(model="gpt-4.1"),
            frozen_builtin_profile(resolve_inference_profile("gpt-4.1", accounting["endpoint"])),
        ),
        (provider_config(inference_profile=profile), profile),
        (provider_config(inference_profile=profile, workflow_accounting=accounting), profile),
    ):
        settings = dict(
            version=1, model=config["model"], endpoint=config["base_url"], billing="free", inference_policy=policy
        )
        if "workflow_accounting" in config:
            settings["workflow_accounting"] = accounting
        expected = hashlib.sha256(
            json.dumps(settings, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        assert model_settings_sha256(config, billing="free") == expected
        public = PublicModelSettings.model_validate({key: value for key, value in settings.items() if key != "version"})
        assert public_model_settings_sha256(public) == expected
        assert model_settings_sha256(config | {"api_key": "ROTATED_SENTINEL_736b"}, billing="free") == expected
        assert model_settings_sha256(config, billing="paid") != expected
        frozen = _config(config)
        assert frozen["api_key"] == PRIVATE and frozen.get("inference_profile") == policy
        if policy is not None:
            assert frozen["inference_profile"] is not policy
        if "workflow_accounting" in config:
            assert frozen["workflow_accounting"] == accounting and frozen["workflow_accounting"] is not accounting

    config = provider_config(inference_profile=profile, workflow_accounting=accounting)
    original = model_settings_sha256(config, billing="free")
    changed_policy = profile | {"request_policy": profile["request_policy"] | {"temperature_mode": "configured"}}
    for changed in (
        config | {"inference_profile": changed_policy},
        config | {"workflow_accounting": accounting | {"max_tokens": 701}},
        config
        | {
            "trusted_server": True,
            "base_url": config["base_url"] + "/",
            "workflow_accounting": accounting | {"endpoint": accounting["endpoint"] + "/"},
        },
    ):
        assert model_settings_sha256(changed, billing="free") != original
    assert model_settings_sha256(provider_config(model="other"), billing="free") != model_settings_sha256(
        provider_config(), billing="free"
    )
    with pytest.raises(ValueError, match="^Invalid workflow accounting attestation$"):
        _config(config | {"workflow_accounting": accounting | {"endpoint": accounting["endpoint"] + "/"}})
    with pytest.raises(ValueError, match="^Invalid provider configuration$"):
        _config(provider_config(base_url="http://localhost/v1", trusted_server=1))
    with pytest.raises(ValueError, match="^Invalid model billing$"):
        model_settings_sha256(config, billing="unknown")


def test_module_entrypoint_inspects_file_without_releasing_execution(tmp_path, capsys, monkeypatch):
    import runpy
    import sys

    path = tmp_path / "request.json"
    path.write_text(json.dumps(request()))
    monkeypatch.delitem(sys.modules, PREFIX + ".cli", raising=False)
    monkeypatch.setattr(sys, "argv", [PREFIX + ".cli", "inspect-contract", str(path)])
    with pytest.raises(SystemExit) as exit_result:
        runpy.run_module(PREFIX + ".cli", run_name="__main__")
    assert exit_result.value.code == 0
    output, error = capsys.readouterr()
    assert error == ""
    result = json.loads(output)
    assert result["execution_released"] is False and result["readiness_checked"] is False
    assert result["required_criteria"] == {"count": 1, "ids": ["layout"]}


def test_inspect_real_file_has_canonical_digest_and_only_public_plan(tmp_path, capsys):
    from isaaclab_arena.agentic_environment_generation.workflow import canonical_json, parse_contract

    raw = request()
    raw["source"]["prompt"] = PRIVATE
    raw["criteria"][0]["rubric"] = PRIVATE
    advisory = copy.deepcopy(raw["criteria"][0])
    advisory.update(criterion_id="advisory", requirement="advisory")
    raw["criteria"].append(advisory)
    path = tmp_path / "request.json"
    path.write_text(json.dumps(raw))
    assert cli().main(["inspect-contract", str(path)]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert PRIVATE not in out
    expected_digest = hashlib.sha256(canonical_json(parse_contract(path.read_bytes())).encode()).hexdigest()
    assert json.loads(out) == {
        "schema_version": "1",
        "contract_digest": expected_digest,
        "required_criteria": {"ids": ["layout"], "count": 1},
        "advisory_criteria": {"ids": ["advisory"], "count": 1},
        "planned_dependencies": [
            {"category": "generation_model", "profile_id": "offline"},
            {"category": "neo4j", "profile_id": "offline"},
            {"category": "runtime", "profile_id": "offline"},
        ],
        "scene_assessment": {"compatible": True, "code": "supported_projection"},
        "execution_released": False,
        "readiness_checked": False,
    }
    assert cli().main(["inspect-contract", str(path)]) == 0
    assert capsys.readouterr().out == out


@pytest.mark.parametrize(
    "case", ["missing", "invalid", "validation", "oversize", "directory", "symlink", "fifo", "utf8", "duplicate"]
)
def test_bad_file_has_static_diagnostic_without_private_input(case, tmp_path, capsys):
    import os

    from isaaclab_arena.agentic_environment_generation.workflow.contracts import MAX_CONTRACT_BYTES

    path = tmp_path / PRIVATE
    if case == "directory":
        path.mkdir()
    elif case == "symlink":
        target = tmp_path / "real.json"
        target.write_text(json.dumps(request()))
        path.symlink_to(target)
    elif case == "fifo":
        os.mkfifo(path)
    elif case != "missing":
        data = {
            "invalid": PRIVATE.encode(),
            "validation": json.dumps({"schema_version": PRIVATE}).encode(),
            "oversize": b" " * (MAX_CONTRACT_BYTES + 1),
            "utf8": b"\xff" + PRIVATE.encode(),
            "duplicate": ('{"' + PRIVATE + '":1,"' + PRIVATE + '":2}').encode(),
        }[case]
        path.write_bytes(data)
    if case == "fifo":
        import signal

        def timeout(*_):
            # Must escape the CLI's OSError handler; otherwise a blocking open
            # would look like the expected static rejection after the alarm.
            raise AssertionError("nonregular input must not block")

        previous = signal.signal(signal.SIGALRM, timeout)
        signal.alarm(1)
        try:
            result = cli().main(["inspect-contract", str(path)])
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
    else:
        result = cli().main(["inspect-contract", str(path)])
    assert result == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err == "inspect-contract: invalid request file\n"
    assert PRIVATE not in err


@pytest.mark.parametrize(
    "args", [[], ["inspect-contract"], ["run", PRIVATE], ["status"], ["inspect-contract", PRIVATE, "--" + PRIVATE]]
)
def test_bad_arguments_are_static_and_no_placeholder_commands(args, capsys):
    assert cli().main(args) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err == "inspect-contract: invalid arguments\n"


def test_unsupported_policy_is_inspected_not_admitted(tmp_path, capsys):
    raw = request()
    raw["criteria"][0].update(kind="policy", required_modalities=["policy_rollout"])
    raw["execution"]["policy"] = raw["execution"]["runtime"]
    raw["effects"]["allow_runtime"] = True
    raw["budget"].update(max_realizations=1, max_steps=1, max_observations=1, max_policy_episodes=1, max_policy_steps=1)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw))
    assert cli().main(["inspect-contract", str(path)]) == 0
    out, err = capsys.readouterr()
    summary = json.loads(out)
    assert err == ""
    assert summary["scene_assessment"] == {"compatible": False, "code": "unsupported_scene_assessment"}
    assert summary["execution_released"] is False
    assert summary["readiness_checked"] is False
    assert {item["category"] for item in summary["planned_dependencies"]} == {
        "runtime",
        "neo4j",
        "generation_model",
        "capture",
        "gpu",
        "policy",
    }


def test_domain_construction_and_cli_do_not_import_or_construct_effects(tmp_path, capsys, monkeypatch):
    import builtins
    import importlib.abc
    import importlib.util
    import sys

    forbidden = (
        "argparse",
        "torch",
        "isaacsim",
        "isaaclab",
        "omni",
        "pxr",
        "neo4j",
        "openai",
        "anthropic",
        "requests",
        "httpx",
        "sqlite3",
        "isaaclab_arena.agentic_environment_generation.workbench.journal",
        "isaaclab_arena_examples",
        "isaaclab_arena.agentic_environment_generation.environment_generation_agent",
        "isaaclab_arena.agentic_environment_generation.inference",
        PREFIX + ".inference_transport",
        "fastapi",
        "strawberry",
        PREFIX + ".service",
        PREFIX + ".coordinator",
        PREFIX + ".neo4j_store",
    )
    attempts = []
    original_import = builtins.__import__

    def check(name):
        if any(name == item or name.startswith(item + ".") for item in forbidden):
            attempts.append(name)
            raise AssertionError("forbidden import attempted")

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        resolved = importlib.util.resolve_name("." * level + name, globals["__package__"]) if level else name
        check(resolved)
        return original_import(name, globals, locals, fromlist, level)

    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            check(fullname)

    for name in tuple(sys.modules):
        if name == PREFIX or name.startswith(PREFIX + "."):
            parent_name, _, child = name.rpartition(".")
            parent = sys.modules.get(parent_name)
            if parent is not None:
                monkeypatch.delattr(parent, child, raising=False)
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(sys, "meta_path", [Guard(), *sys.meta_path])
    domain = importlib.import_module(PREFIX)
    contract = domain.WorkflowContract.model_validate(request())
    assert domain.parse_contract(domain.canonical_json(contract)) == contract
    readiness = importlib.import_module(PREFIX + ".readiness")
    projection = importlib.import_module(PREFIX + ".evidence_contracts")
    assert readiness.required_dependencies(contract)
    assert projection.project_required_criteria(contract)
    assert PREFIX + ".cli" not in sys.modules
    # This contract stays transport/store-independent even when imported cold.
    from isaaclab_arena.agentic_environment_generation.workflow import queries
    from isaaclab_arena.agentic_environment_generation.workflow.commands import ResumePayload, ResumeReceipt

    assert (
        ResumePayload(runId="literal.Run:1", expectedVersion=2**40, renewAuthorization=False).runId == "literal.Run:1"
    )
    assert ResumeReceipt.model_fields["selection"] and ResumeReceipt.model_fields["contract_digest"]
    assert queries.SceneDecisionView.model_fields["selected_assessment_id"]
    assert queries.RunCleanupView.model_fields["projection_revision"]
    assert queries.IntentCleanupView.model_fields["registration_id"]
    assert "registration" not in queries.IntentCleanupView.model_fields
    assert "clean" not in queries.RunCleanupView.model_fields
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import (
        ProfileRegistration,
        public_model_settings_sha256,
    )
    from isaaclab_arena.tests.test_environment_workflow_store import profile_registration

    raw_profile = profile_registration()
    raw_profile["settings"]["workflow_accounting"] = {
        "version": 1, "attested": True, "model": "gpt-4.1", "endpoint": "https://api.openai.com/v1/",
        "max_tokens": 700, "max_cost_usd": "0",
    }
    public_profile = ProfileRegistration.model_validate(raw_profile)
    assert len(public_model_settings_sha256(public_profile.settings)) == 64
    assert attempts == []

    # Cold admin/service/store construction may load repository code, but never
    # a database driver, SDK, SQLite, transport, web stack, or credentials.
    forbidden = tuple(name for name in forbidden if name not in (PREFIX + ".service", PREFIX + ".neo4j_store"))
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowProfileAdmin, WorkflowService

    class NoPorts:
        def __getattr__(self, name):
            raise AssertionError("cold construction touched an external port")

    ports = NoPorts()
    store = Neo4jWorkflowStore(ports, database="db", deployment_id="dep", workspace_id="workspace")
    WorkflowProfileAdmin(store, ports)
    WorkflowService(store, ports, ports, validate_support=ports)
    assert attempts == []

    # argparse is allowed only after entering the CLI module, never in the domain.
    forbidden = tuple(name for name in forbidden if name != "argparse")

    def no_effects(*args, **kwargs):
        raise AssertionError("readiness probe or effect construction attempted")

    monkeypatch.setattr(readiness.DependencyGate, "__init__", no_effects)
    monkeypatch.setattr(readiness, "durable_readiness", no_effects)
    entry = importlib.import_module(PREFIX + ".cli")
    raw = request()
    raw["source"] = {"kind": "existing", "identity": "scene", "content": PRIVATE}
    path = tmp_path / "existing.json"
    path.write_text(json.dumps(raw))
    assert entry.main(["inspect-contract", str(path)]) == 0
    out, err = capsys.readouterr()
    assert err == "" and PRIVATE not in out
    assert json.loads(out)["planned_dependencies"] == [
        {"category": "neo4j", "profile_id": "offline"},
        {"category": "runtime", "profile_id": "offline"},
    ]
    assert attempts == []


@pytest.mark.parametrize("fault", [None, "conflict", "outage", "unknown", "cleanup"])
def test_keyed_handler_auth_stop_database_order_and_known_receipt(fault):
    from threading import RLock
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.application import ForegroundWorkflow
    from isaaclab_arena.agentic_environment_generation.workflow.commands import (
        CommandConflict,
        LocalStopObservation,
        command_digest,
        command_json,
        make_cancel_receipt,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown, StoreUnavailable

    assert hasattr(ForegroundWorkflow, "cancel_keyed"), "shared keyed cancel handler missing"
    calls = []
    payload = command_json({"runId": "run"})
    receipt = make_cancel_receipt(
        scope=dict(database="db", deployment_id="d", workspace_id="w"),
        operation_id="key",
        run_id="run",
        payload_json=payload,
        payload_digest=command_digest(payload),
        before_version=1,
        after_version=2,
        disposition="cancellation_requested",
        reason=None,
        first_local_stop=LocalStopObservation(delivery="no_owner").model_dump(),
        events=[dict(sequence=2, kind="CancellationRequested", source_id="run")],
    )

    def durable(key, run, local, *, protect):
        assert calls[:3] == ["read_auth", "cancel_auth", "stop"]
        assert local.delivery == "delivered"
        calls.append("db")
        if fault in {"conflict", "outage", "unknown"}:
            raise {"conflict": CommandConflict, "outage": StoreUnavailable, "unknown": OutcomeUnknown}[fault]("private")
        return receipt

    def finish(*args):
        calls.append("finish")
        if fault == "cleanup":
            raise OSError("private")

    app = ForegroundWorkflow.__new__(ForegroundWorkflow)
    app._closed, app._lock, app._local = False, RLock(), {"run": object()}
    app.authority = SimpleNamespace(require_read=lambda p: calls.append("read_auth"), protect_public=lambda v: None)
    app.store = SimpleNamespace(cancel_command=durable, get_run_cleanup=lambda r: None)
    app._cancellation = SimpleNamespace(
        stop_only=lambda *args: (calls.append("stop") or LocalStopObservation(delivery="delivered")),
        finish_cancelled=finish,
    )
    result = app.cancel_keyed("p", "key", "run", authorize_cancel=lambda *args: calls.append("cancel_auth"))
    assert result.local_stop.delivery == "delivered" and result.remote_effects == "unknown"
    assert result.durable == (
        "conflict" if fault == "conflict" else "unknown" if fault in {"outage", "unknown"} else "recorded"
    )
    assert result.receipt == (None if fault in {"conflict", "outage", "unknown"} else receipt)
    assert ("finish" in calls) == (fault not in {"conflict", "outage", "unknown"})
    if fault == "cleanup":
        assert result.cleanup_status == "unavailable"
    assert "private" not in result.model_dump_json()


@pytest.mark.parametrize(
    "fault",
    [
        "cleanup_screen",
        "cleanup_mutate",
        "envelope_screen",
        "envelope_mutate",
        "cleanup_invalid",
        "envelope_budget",
        "receipt_screen",
    ],
)
def test_keyed_handler_cleanup_protection_preserves_known_receipt(fault):
    from threading import RLock
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.application import ForegroundWorkflow
    from isaaclab_arena.agentic_environment_generation.workflow.commands import (
        LocalStopObservation,
        command_digest,
        command_json,
        make_cancel_receipt,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.queries import RunCleanupView
    from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import canonical

    payload = command_json({"runId": "run"})
    receipt = make_cancel_receipt(
        scope=dict(database="db", deployment_id="d", workspace_id="w"),
        operation_id="key",
        run_id="run",
        payload_json=payload,
        payload_digest=command_digest(payload),
        before_version=1,
        after_version=2,
        disposition="cancellation_requested",
        reason=None,
        first_local_stop=LocalStopObservation(delivery="delivered").model_dump(),
        events=[dict(sequence=2, kind="CancellationRequested", source_id="run")],
    )
    cleanup = RunCleanupView(
        scope=dict(database="db", deployment_id="d", workspace_id="private-cleanup-sentinel"),
        run_id="run",
        run_version=2,
        current_scope_owner=None,
        intents=(),
        projection_revision="a" * 64,
    )
    if fault == "envelope_budget":
        cleanup = cleanup.model_copy(
            update={"scope": cleanup.scope.model_copy(update={"workspace_id": "x" * (2 * 1024 * 1024 - 512)})}
        )
        canonical(cleanup.model_dump(mode="json"))  # Cleanup fits alone; joined response does not.
    if fault == "cleanup_invalid":
        cleanup = cleanup.model_copy(update={"run_version": "private-cleanup-sentinel"})
    original = cleanup.model_dump_json()
    screens = []

    def protect(value):
        screens.append(value)
        envelope = "durable" in value
        if fault == "receipt_screen" and ("receipt_digest" in value or envelope):
            raise PermissionError("receipt denied")
        target = value.get("cleanup") if envelope else value if "projection_revision" in value else None
        if target is not None and fault in ("cleanup_screen", "envelope_screen"):
            if fault == "cleanup_screen" or envelope:
                raise PermissionError("private-cleanup-sentinel")
        if target is not None and fault in ("cleanup_mutate", "envelope_mutate"):
            if fault == "cleanup_mutate" or envelope:
                target["scope"]["workspace_id"] = "mutated-private-cleanup-sentinel"

    app = ForegroundWorkflow.__new__(ForegroundWorkflow)
    app._closed, app._lock, app._local = False, RLock(), {}
    app.authority = SimpleNamespace(require_read=lambda p: None, protect_public=protect)
    app.store = SimpleNamespace(cancel_command=lambda *a, **kw: receipt, get_run_cleanup=lambda r: cleanup)
    app._cancellation = SimpleNamespace(stop_only=lambda *a: LocalStopObservation(delivery="delivered"))
    if fault == "receipt_screen":
        with pytest.raises(PermissionError, match="receipt denied"):
            app.cancel_keyed("p", "key", "run", authorize_cancel=lambda *a: None)
    else:
        result = app.cancel_keyed("p", "key", "run", authorize_cancel=lambda *a: None)
        assert result.durable == "recorded" and result.receipt == receipt
        assert result.cleanup_status == "unavailable" and result.cleanup is None
        assert "private-cleanup-sentinel" not in result.model_dump_json()
        assert screens[-1] == result.model_dump(mode="json"), "whole fallback must be screened"
    assert cleanup.model_dump_json() == original, "protection must only receive detached cleanup"


@pytest.mark.parametrize("failure", ["read", "cancel", "missing_authority", "bad_key", "bad_run", "screen", "mutate"])
def test_keyed_handler_refuses_before_local_stop_or_key_binding(failure):
    from threading import RLock
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.application import ForegroundWorkflow

    calls = []

    def read(principal):
        calls.append("read")
        if failure == "read":
            raise PermissionError("denied")

    def authorize(principal, run_id):
        calls.append("cancel")
        if failure == "cancel":
            raise PermissionError("denied")

    def protect(value):
        if failure == "screen":
            raise PermissionError("denied")
        if failure == "mutate":
            value["runId"] = "other"

    def forbidden(*args, **kwargs):
        pytest.fail("denied cancellation must not stop, bind a key, probe or resolve grants")

    app = ForegroundWorkflow.__new__(ForegroundWorkflow)
    app._closed, app._lock, app._local = False, RLock(), {}
    app.authority = SimpleNamespace(require_read=read, protect_public=protect)
    app.store = SimpleNamespace(cancel_command=forbidden)
    app._cancellation = SimpleNamespace(stop_only=forbidden)
    with pytest.raises((ValueError, PermissionError)):
        app.cancel_keyed(
            "reader",
            "bad key" if failure == "bad_key" else "key",
            "bad run" if failure == "bad_run" else "run",
            authorize_cancel=None if failure == "missing_authority" else authorize,
        )
    assert calls[0] == "read"


def test_graphql_dependency_metadata_only_probe():
    """Record bounded image metadata, not imports, compatibility or permission."""
    import importlib.metadata
    import os
    import re
    import stat
    import sys
    import sysconfig
    from email.parser import BytesParser
    from pathlib import Path

    targets = {"strawberry-graphql": "strawberry", "graphql-core": "graphql",
               "fastapi": "fastapi", "uvicorn": "uvicorn", "httpx": "httpx"}
    limits = dict(roots=128, entries_per_root=4096, metadata_files=64,
                  metadata_bytes=262144, total_metadata_bytes=8388608, report_bytes=524288)
    before_modules = set(sys.modules)
    normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
    report = {
        "schema_version": 1,
        "scope": "metadata and immediate package paths only; absence is confined to searched roots",
        "not_established": ["importability", "GraphQL/API compatibility", "new execution permission"],
        "limits": limits,
        "interpreter": {"executable": sys.executable, "version": sys.version,
                        "prefix": sys.prefix, "base_prefix": sys.base_prefix},
        "root_policy": "sysconfig purelib/platlib plus absolute sys.path directories under /isaac-sim, /opt, /usr; "
                       "no symlink traversal; readonly image paths only; no recursive search or entrypoints",
        # The runner binds the inspected immutable image and exact mount list in
        # run-proof.json. These prefixes exclude its source/evidence/tmp/private mounts.
        "roots": [], "excluded_sys_path": [], "metadata_files_read": 0, "metadata_bytes_read": 0,
    }

    def path_state(path):
        """Lstat each component before proceeding, never dereference a link."""
        current = Path("/")
        for part in path.parts[1:]:
            current /= part
            try:
                info = current.lstat()
            except FileNotFoundError:
                return {"state": "missing", "at": str(current)}
            except OSError as error:
                return {"state": "probe_failure", "error_type": type(error).__name__}
            if stat.S_ISLNK(info.st_mode):
                return {"state": "symlink", "at": str(current)}
            if current != path and not stat.S_ISDIR(info.st_mode):
                return {"state": "non_directory_ancestor", "at": str(current)}
        return {"state": "directory" if stat.S_ISDIR(info.st_mode) else
                "regular_file" if stat.S_ISREG(info.st_mode) else "other",
                "device": info.st_dev, "inode": info.st_ino, "mode": info.st_mode,
                "uid": info.st_uid, "size": info.st_size}

    candidates = {}
    for key in ("purelib", "platlib"):
        candidates.setdefault(sysconfig.get_path(key), []).append("sysconfig." + key)
    assert len(sys.path) <= limits["roots"], "Bound sys.path before discovery"
    for index, value in enumerate(sys.path):
        path = Path(value)
        if path.is_absolute() and path.parts[1:2] in (("isaac-sim",), ("opt",), ("usr",)):
            candidates.setdefault(value, []).append("sys.path:" + str(index))
        else:
            report["excluded_sys_path"].append({"index": index, "path": value,
                                                "reason": "outside immutable image prefixes"})
    assert len(candidates) <= limits["roots"]
    for value, origins in candidates.items():
        path = Path(value)
        root = {"path": value, "origins": origins, "targets": {}, "metadata_search": "unsearched"}
        report["roots"].append(root)
        if (not path.is_absolute() or ".." in path.parts or len(path.parts) > 24 or
                path.parts[1:2] not in (("isaac-sim",), ("opt",), ("usr",))):
            root["identity"] = {"state": "excluded"}
            continue
        root["identity"] = path_state(path)
        if root["identity"]["state"] != "directory":
            continue
        try:
            root["readonly"] = bool(os.statvfs(path).f_flag & os.ST_RDONLY)
            if not root["readonly"]:
                root["metadata_search"] = "excluded_mutable"
                continue
            for name, package in targets.items():
                root["targets"][name] = {"package_path": str(path / package),
                                         "package": path_state(path / package),
                                         "distribution_metadata": [], "metadata_status": "unsearched"}
            # Bound listing before importlib.metadata's nonrecursive discovery.
            count = 0
            with os.scandir(path) as entries:
                for entry in entries:
                    count += 1
                    if count > limits["entries_per_root"]:
                        raise ValueError("root entry bound")
            root["entries"] = count
            discovered = 0
            for distribution in importlib.metadata.distributions(path=[str(path)]):
                discovered += 1
                if discovered > limits["entries_per_root"]:
                    raise ValueError("distribution bound")
                # Discovery alone does not read METADATA. Do not use .metadata,
                # .files or entry_points: they can follow unchecked fallback paths.
                metadata_dir = distribution._path
                if not isinstance(metadata_dir, Path) or metadata_dir.parent != path:
                    raise ValueError("non-immediate distribution path")
                stem = metadata_dir.name
                suffix = next((item for item in (".dist-info", ".egg-info") if stem.endswith(item)), None)
                if suffix is None:
                    continue
                normalized = normalize(stem[:-len(suffix)])
                name = next((item for item in targets if normalized == item or
                             normalized.startswith(item + "-")), None)
                if name is None:
                    continue
                result = {"path": str(metadata_dir), "identity": path_state(metadata_dir)}
                root["targets"][name]["distribution_metadata"].append(result)
                if result["identity"]["state"] != "directory":
                    result["status"] = result["identity"]["state"]
                    continue
                metadata_file = metadata_dir / ("METADATA" if suffix == ".dist-info" else "PKG-INFO")
                result["metadata_file"] = str(metadata_file)
                result["file_identity"] = path_state(metadata_file)
                if result["file_identity"]["state"] != "regular_file":
                    result["status"] = result["file_identity"]["state"]
                    continue
                if (result["file_identity"]["size"] > limits["metadata_bytes"] or
                        report["metadata_files_read"] >= limits["metadata_files"] or
                        report["metadata_bytes_read"] + result["file_identity"]["size"] >
                        limits["total_metadata_bytes"]):
                    result["status"] = "probe_failure"
                    result["error_type"] = "metadata_bound"
                    continue
                # Ancestors are no-follow checked on the verified readonly image;
                # O_NOFOLLOW additionally protects the leaf read.
                fd = os.open(metadata_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    assert stat.S_ISREG(info.st_mode) and info.st_ino == result["file_identity"]["inode"]
                    data = stream.read(limits["metadata_bytes"] + 1)
                assert len(data) <= limits["metadata_bytes"]
                report["metadata_files_read"] += 1
                report["metadata_bytes_read"] += len(data)
                headers = BytesParser().parsebytes(data, headersonly=True)
                names, versions = headers.get_all("Name", []), headers.get_all("Version", [])
                if (len(names) != 1 or len(versions) != 1 or normalize(names[0]) != name or
                        not re.fullmatch(r"[A-Za-z0-9_.+!-]{1,128}", versions[0])):
                    result["status"] = "probe_failure"
                    result["error_type"] = "invalid_name_version"
                    continue
                result.update(status="present", name=names[0], version=versions[0],
                              sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
            root["distributions_discovered"] = discovered
            root["metadata_search"] = "complete_standard_dist_info_egg_info_names"
            for result in root["targets"].values():
                records = result["distribution_metadata"]
                result["metadata_status"] = ("present" if any(r["status"] == "present" for r in records)
                                             else "unresolved_metadata" if records else "absent_in_root")
        except (OSError, ValueError, AssertionError) as error:
            root["metadata_search"] = "probe_failure"
            root["error_type"] = type(error).__name__
            for result in root["targets"].values():
                result["metadata_status"] = "probe_failure"

    report["new_target_modules"] = sorted(name for name in set(sys.modules) - before_modules
                                         if name.split(".")[0] in set(targets.values()))
    report["coverage"] = {
        "searched_roots": [r["path"] for r in report["roots"] if r["metadata_search"].startswith("complete_")],
        "unsearched_roots": [r["path"] for r in report["roots"] if not r["metadata_search"].startswith("complete_")],
        "limitations": "No global absence claim; no recursive directories, archive roots, symlink targets, "
                       "nonstandard metadata names, dependency resolution, package code or entrypoint loading",
    }
    # Validate the observation schema and bounds, never require availability.
    assert report["schema_version"] == 1 and report["new_target_modules"] == []
    assert report["metadata_files_read"] <= limits["metadata_files"]
    assert report["metadata_bytes_read"] <= limits["total_metadata_bytes"]
    assert len(report["roots"]) <= limits["roots"]
    for root in report["roots"]:
        assert root["metadata_search"] in {"unsearched", "excluded_mutable", "probe_failure",
                                           "complete_standard_dist_info_egg_info_names"}
        for result in root["targets"].values():
            assert result["metadata_status"] in {"unsearched", "present", "unresolved_metadata",
                                                 "absent_in_root", "probe_failure"}
            assert result["package"]["state"] in {"directory", "symlink", "missing", "regular_file",
                                                  "other", "non_directory_ancestor", "probe_failure"}
    encoded = json.dumps(report, indent=2, sort_keys=True).encode("utf-8")
    assert len(encoded) <= limits["report_bytes"]
    output = Path("/evidence/graphql-dependency-metadata.json")
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)
