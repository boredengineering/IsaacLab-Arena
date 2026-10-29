# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Installed request/pricing bindings; all rates are fictional test fixtures."""

import copy
import json
import unittest
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import patch


def synthetic_bounds():
    """Explicit fictional universal prices, not a production provider rate source."""
    return {
        "version": 1,
        "envelope": {
            "version": 1,
            "max_text_bytes": 100000,
            "max_schema_bytes": 100000,
            "max_request_bytes": 300000,
            "output_parameter": "max_completion_tokens",
            "max_output_tokens": 64,
            "image_formats": ["png"],
            "max_images": 2,
            "max_image_bytes": 4096,
            "max_image_width": 8,
            "max_image_height": 8,
            "image_detail": "auto",
            "permitted_fields": ["model", "messages", "max_completion_tokens", "store", "response_format"],
            "route_policy": "direct-chat-completions-v1",
        },
        "pricing": {
            "version": 1,
            "revision": "synthetic-price-1",
            "kind": "synthetic_fixture",
            "source": "urn:arena:synthetic-pricing-fixture:v1",
            "provider": "openai",
            "input_tokens_per_request_byte": 1,
            "image_tokens_per_image": 1024,
            "input_usd_per_million_tokens": "1",
            "output_usd_per_million_tokens": "2",
            "per_request_usd": "0.001",
            "assumptions": [
                "Fictional rates and token bounds for deterministic transport only; no live billing guarantee.",
                "Every admitted request byte bounds text, catalogue, schema, prior, repair and message overhead.",
                "Each image allowance covers the admitted dimensions and auto detail worst case.",
                "Output allowance includes default reasoning; failed transmissions incur the full bound.",
            ],
        },
    }


def bounded_registration():
    from workflow_graphql_execution_join_fixture import registrations

    from isaaclab_arena.agentic_environment_generation.workflow.request_envelope import RequestBounds

    value = registrations()[0].model_dump(mode="json")
    value["revision"] = 2
    value["settings"]["billing"] = "paid"
    value["settings"]["request_bounds"] = synthetic_bounds()
    bounds = RequestBounds.model_validate(value["settings"]["request_bounds"])
    value["settings"]["workflow_accounting"] = bounds.accounting(
        model=value["settings"]["model"], endpoint=value["settings"]["endpoint"]
    )
    return value


@contextmanager
def serialized_client(**options):
    """Real SDK serialization with only the HTTP transport replaced."""
    import importlib
    import time

    import openai._base_client
    from openai import DefaultHttpxClient

    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import CallAllowance, bounded_client
    from isaaclab_arena.agentic_environment_generation.workflow.request_envelope import RequestBounds

    settings = bounded_registration()["settings"]
    config = dict(
        api_key="unit-private-bound-source", model=settings["model"], base_url=settings["endpoint"],
        inference_profile=settings["inference_policy"], workflow_accounting=settings["workflow_accounting"],
        request_bounds=settings["request_bounds"],
    )
    envelope = RequestBounds.model_validate(config["request_bounds"]).bind(
        model=config["model"], endpoint=config["base_url"], accounting=config["workflow_accounting"],
        inference_policy=config["inference_profile"],
    )
    allowance = CallAllowance(
        max_calls=2, deadline=time.monotonic() + 30, max_tokens=2 * config["workflow_accounting"]["max_tokens"],
        cost_ceiling_usd=str(2 * Decimal(config["workflow_accounting"]["max_cost_usd"])),
        per_call_bound=config["workflow_accounting"],
    )
    with DefaultHttpxClient(trust_env=False) as http:
        transport_type = type(http._transport)
    httpx = importlib.import_module(transport_type.__module__.split(".")[0])
    sends = []

    def response(transport, request):
        sends.append(json.loads(request.content))
        return httpx.Response(200, request=request, json=dict(
            id="synthetic-only", object="chat.completion", created=0, model=config["model"],
            choices=[dict(index=0, finish_reason="stop", message=dict(role="assistant", content="pong"))],
        ))

    with patch.object(openai._base_client, "get_platform", lambda: "Linux"), patch.object(
        transport_type, "handle_request", response
    ), bounded_client(config, allowance=allowance, request_envelope=envelope, **options) as client:
        yield client, allowance, sends, config


class ProviderBounds(unittest.TestCase):
    def test_budget_refusal_releases_only_proven_never_prepared_cancelled_owner(self):
        import tempfile
        from threading import RLock
        from types import SimpleNamespace

        from isaaclab_arena_examples.agentic_environment_generation.foreground_cancellation import finish_cancelled
        from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease

        for mode in ("unused", "busy", "prepared", "dirty_owner", "claimed", "not_cancelled"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                lease = ForegroundOwnerLease(directory, run_id="run", principal="operator", cleanup_verified=lambda *a: False)
                if mode == "prepared":
                    lease.mark_prepared(object())  # Unit-only latch: no actual worker is created.
                handle = SimpleNamespace(prepared=None, fence=None, owner_epoch=None)
                local = SimpleNamespace(principal="operator", retired=False, stopped=False, busy=mode == "busy",
                                        coordinator=SimpleNamespace(stop_local=lambda p: SimpleNamespace(cleanup_pending=False)),
                                        ports=None, handle=handle, lease=lease)
                store = SimpleNamespace(
                    get_run=lambda r: SimpleNamespace(state="pending" if mode == "not_cancelled" else "cancelled"),
                    get_owner=lambda: SimpleNamespace(dirty=True) if mode == "dirty_owner" else None,
                    get_generation_attempt=lambda r: object() if mode == "claimed" else None,
                )
                app = SimpleNamespace(_lock=RLock(), _local={"run": local}, store=store,
                                      _cancel_controls={"run": SimpleNamespace(principal="operator", stopped=False)})
                try:
                    self.assertEqual(finish_cancelled(app, "operator", "run", local), mode == "unused")
                    self.assertEqual(lease._released, mode == "unused")
                    self.assertEqual(local.retired, mode == "unused")
                finally:
                    if not lease._released:
                        lease._lease.__exit__(None, None, None)  # Teardown of this worker-free unit fixture only.

    def test_parent_send_reply_is_current_bounded_and_one_shot(self):
        import os
        import time
        from types import SimpleNamespace

        from isaaclab_arena.agentic_environment_generation.workflow.coordinator import PreparedWorker
        from isaaclab_arena_examples.agentic_environment_generation.foreground_generation import _Owned
        from isaaclab_arena_examples.agentic_environment_generation.foreground_scene import ForegroundSceneWorker

        self.assertTrue(hasattr(ForegroundSceneWorker, "bind_model_send"), "parent current-authority reply missing")
        read, write = os.pipe()
        current, checked = [True], []
        worker = ForegroundSceneWorker()
        with os.fdopen(write, "wb", buffering=0) as channel:
            owned = _Owned(SimpleNamespace(stdin=channel), None, registration=object(), deadline=time.monotonic() + 5)
            owned.model_send_config = {"binding": "fixed"}
            owned.model_send_allowance = SimpleNamespace(max_calls=2)
            worker._owned.append(owned)
            prepared = PreparedWorker(owned.registration, owned)

            @contextmanager
            def guard(config):
                self.assertEqual(config, {"binding": "fixed"})
                checked.append(current[0])
                if not current[0]:
                    raise ValueError("Current authority revoked")
                yield

            worker.bind_model_send(prepared, guard)
            message = dict(version=1, ordinal=1, request_sha256="a" * 64)
            try:
                worker._answer_model_send(owned, message)
                self.assertEqual(json.loads(os.read(read, 1024)), {"model_send_ack": message})
                with self.assertRaises(ValueError):
                    worker._answer_model_send(owned, message)
                current[0] = False
                with self.assertRaises(ValueError):
                    worker._answer_model_send(owned, dict(message, ordinal=2))
                self.assertEqual(checked, [True, False])
                os.set_blocking(read, False)
                with self.assertRaises(BlockingIOError):
                    os.read(read, 1024)
            finally:
                os.close(read)

    def test_worker_send_authorization_requires_exact_reply_and_never_reuses_it(self):
        import hashlib
        import io
        import time
        from types import SimpleNamespace

        from isaaclab_arena_examples.agentic_environment_generation.web_api import scene_worker

        self.assertTrue(hasattr(scene_worker, "ModelSendAuthorization"), "owned-pipe send authorization missing")
        request = SimpleNamespace(content=b'{"model":"synthetic-only"}')
        message = dict(version=1, ordinal=1, request_sha256=hashlib.sha256(request.content).hexdigest())
        reply = (json.dumps({"model_send_ack": message}, separators=(",", ":")) + "\n").encode()
        channel = io.StringIO()
        allowance = SimpleNamespace(max_calls=2, deadline=time.monotonic() + 5)
        sender = scene_worker.ModelSendAuthorization(channel, io.BytesIO(reply), allowance)
        sender(request)
        self.assertEqual(json.loads(channel.getvalue()), {"model_send": message})
        self.assertEqual(sender.approved_calls, 1)
        with self.assertRaises(ValueError):
            sender(request)
        self.assertEqual(sender.approved_calls, 1)

    def test_send_guard_rechecks_after_sdk_preparation_and_keeps_probe_charge(self):
        import inspect

        from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import bounded_client

        self.assertIn("send_guard", inspect.signature(bounded_client).parameters, "final send authority hook missing")
        current, checks = [True], []

        def guard(request):
            checks.append(json.loads(request.content)["max_completion_tokens"])
            if not current[0]:
                raise ValueError("Synthetic current authority withdrawn")

        with serialized_client(send_guard=guard) as (client, allowance, sends, config):
            arguments = dict(model=config["model"], messages=[dict(role="user", content="probe")], store=False)
            client.chat.completions.create(**arguments, max_completion_tokens=8)

            def revoke(request):
                current[0] = False

            with patch.object(client, "_prepare_request", revoke), self.assertRaises(Exception):
                client.chat.completions.create(**arguments, max_completion_tokens=64)
            self.assertEqual(checks, [8, 64])
            self.assertEqual(len(sends), 1)
            self.assertEqual(allowance.attempted_calls, 2)
            self.assertEqual(allowance.charged_cost_usd, 2 * Decimal(config["workflow_accounting"]["max_cost_usd"]))

    def test_expiry_after_serialization_denies_transport_without_refund(self):
        with serialized_client() as (client, allowance, sends, config):
            def expire(request):
                allowance._deadline = 0.0

            with patch.object(client, "_prepare_request", expire), self.assertRaises(Exception):
                client.chat.completions.create(
                    model=config["model"], messages=[dict(role="user", content="boundary")],
                    max_completion_tokens=64, store=False,
                )
            self.assertEqual(sends, [])
            self.assertEqual(allowance.attempted_calls, 1)
            self.assertEqual(allowance.charged_tokens, config["workflow_accounting"]["max_tokens"])
            self.assertGreater(allowance.charged_cost_usd, 0)

    def test_grants_validate_public_bounds_without_misclassifying_them_as_secrets(self):
        from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants

        value = bounded_registration()["settings"]
        config = dict(
            api_key="unit-private-bound-source", model=value["model"], base_url=value["endpoint"],
            inference_profile=value["inference_policy"], workflow_accounting=value["workflow_accounting"],
            request_bounds=value["request_bounds"],
        )
        grants = ExecutionGrants(clock=lambda: 1.0)
        public = grants.issue("reader", "run", "model", dict(profile_id="generation"), config, 10.0)
        grants.protect_public(value)
        self.assertEqual(grants.resolve("reader", public["grant_id"], "run", "model"), config)
        with self.assertRaises(ValueError):
            grants.protect_public({"secret": config["api_key"]})
        config["request_bounds"]["pricing"]["input_usd_per_million_tokens"] = "unknown"
        with self.assertRaises(ValueError):
            grants.issue("reader", "other-run", "model", dict(profile_id="generation"), config, 10.0)

    def test_private_roles_and_execution_hash_retain_the_registered_bounds(self):
        from isaaclab_arena.agentic_environment_generation.workflow.api.installed_composition import Resources
        from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load
        from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration, profile_revision
        from isaaclab_arena.tests.test_workflow_operator_setup import operator_configuration, private_setup
        from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import model_settings_sha256

        with operator_configuration() as (path, public, credentials):
            profiles = []
            for role in ("generation", "assessment"):
                value = bounded_registration()
                value.update(profile_id=role, roles=[role + "_model"])
                profiles.append(ProfileRegistration.model_validate(value))
            public["required_profiles"] = [profile_revision(p).model_dump(mode="json") for p in profiles]
            for role in ("generation", "assessment", "repair"):
                public["role_bindings"][role]["profile"] = profiles[role == "assessment"].model_dump(mode="json")
            path.write_text(json.dumps(public))
            self.assertEqual(private_setup(path, credentials)[0], 0)
            resource = Resources(load(str(path)))
            for role in ("generation", "assessment", "repair"):
                config = resource.private_roles().model_config(role)
                self.assertEqual(config.get("request_bounds"), synthetic_bounds())
                self.assertEqual(
                    model_settings_sha256(config, billing="paid"),
                    profile_revision(profiles[role == "assessment"]).settings_sha256,
                )

    def test_registered_price_derivation_roundtrips_and_binds_every_assumption(self):
        from isaaclab_arena.agentic_environment_generation.workflow import request_envelope
        from isaaclab_arena.agentic_environment_generation.workflow.profiles import ProfileRegistration, profile_revision

        self.assertTrue(hasattr(request_envelope, "RequestBounds"), "installed request/pricing binding missing")
        value = bounded_registration()
        profile = profile_revision(ProfileRegistration.model_validate(value))
        settings = profile.registration.settings
        bounds = settings.request_bounds
        expected_input = bounds.envelope.max_request_bytes + 2 * bounds.pricing.image_tokens_per_image
        self.assertEqual(settings.workflow_accounting.max_tokens, expected_input + bounds.envelope.max_output_tokens)
        self.assertEqual(
            Decimal(settings.workflow_accounting.max_cost_usd),
            (Decimal(expected_input) + 2 * bounds.envelope.max_output_tokens) / 1000000 + Decimal("0.001"),
        )
        self.assertEqual(type(profile).model_validate_json(profile.model_dump_json()), profile)
        envelope = bounds.bind(
            model=settings.model,
            endpoint=settings.endpoint,
            accounting=settings.workflow_accounting.model_dump(mode="json"),
            inference_policy=settings.inference_policy.model_dump(mode="json"),
        )
        self.assertEqual(envelope.max_output_tokens, 64)
        for part, field, replacement in (
            ("pricing", "revision", "synthetic-price-2"),
            ("pricing", "source", "urn:arena:synthetic-pricing-fixture:alternative"),
            ("pricing", "assumptions", ["Different explicit synthetic assumption"]),
            ("envelope", "max_text_bytes", 99999),
        ):
            changed = copy.deepcopy(value)
            changed["settings"]["request_bounds"][part][field] = replacement
            revised = profile_revision(ProfileRegistration.model_validate(changed))
            with self.subTest(part=part, field=field):
                self.assertNotEqual(revised.settings_sha256, profile.settings_sha256)
                self.assertNotEqual(revised.body_sha256, profile.body_sha256)
        self.assertNotIn("api_key", json.dumps(value))
