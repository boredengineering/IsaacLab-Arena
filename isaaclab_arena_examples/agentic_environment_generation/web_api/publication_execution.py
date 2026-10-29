# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Synchronous, trusted publication coordinator; no routes, workers, or recovery.

PublicationExecutor(store, attempts, authorization, *, driver_factory=None,
transport=research_graph_transport) borrows all component lifetimes. Attempts must
already use this authorization object and the store's Journal/registry.
publish(session, effect_id, request_id) and reconcile(session, effect_id, request_id)
return {accepted: immutable claim snapshot, state: current durable snapshot}.
A previously accepted request is observation only, even if its worker never ran.
Unknown writes require a NEW explicit read request, never renewal or a second write.
Errors propagate; inspect attempts.get_state(effect_id) for the durable outcome.

Call only from a trusted serialized coordinator with authenticated session/request
ownership (not directly as a public route). The read-only binding lookup is needed
because core exposes acceptance replay through claim, but no get-acceptance API.
No private connection or grant is retained by this adapter. Driver factories accept
explicit uri/user/password and bounded SDK options, never ambient configuration.
Transport injection is trusted test infrastructure, NOT a user-supplied callback.
"""

import json

from isaaclab_arena.agentic_environment_generation.workbench import research_graph_transport
from isaaclab_arena.agentic_environment_generation.workbench.research_registry import (
    canonical_json,
    checked_identifier,
    digest,
)

from .publication_payload import (
    checked_frozen_config,
    expected_receipt,
    prepare_publication,
    receipt_envelope,
    transport_once,
)


class PublicationExecutor:
    """Bridge frozen local artifacts to one explicitly authorized fenced graph call."""

    def __init__(
        self,
        store,
        attempts,
        authorization,
        *,
        driver_factory=None,
        transport=research_graph_transport,
    ):
        if (
            attempts.authorizer is not authorization
            or attempts.journal is not store.registry.journal
            or attempts.registry.journal is not attempts.journal
            or attempts.registry.registry_id != store.registry.registry_id
        ):
            raise ValueError("Publication component binding conflict")
        self.store, self.attempts, self.authorization = store, attempts, authorization
        self.driver_factory, self.transport = driver_factory, transport

    def publish(self, session, effect_id, request_id):
        """Explicitly approve and execute one write; accepted replay never dispatches."""
        return self._run(session, effect_id, request_id, "graph_write")

    def reconcile(self, session, effect_id, request_id):
        """Explicitly approve one read-only reconciliation of an unknown publication."""
        return self._run(session, effect_id, request_id, "graph_read")

    def _prepare(self, effect_id):
        return prepare_publication(self.store, self.authorization, effect_id)

    def _replay(self, effect_id, request_id, capability):
        journal = self.attempts.journal
        with journal._lock:
            row = journal.db.execute(
                "SELECT body FROM publication_bindings WHERE request_id=?",
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        record = json.loads(row[0])
        binding = record["binding"]
        intent = self.store.registry.get_publication_intent(effect_id)
        if (
            binding["effect_id"] != effect_id
            or binding["intent_sha256"] != digest(intent)
            or binding["grant_metadata"]["capability"] != capability
        ):
            raise ValueError("Publication request conflict")
        self.store.get_reservation(intent["reservation_id"])
        return dict(accepted=record["accepted"], state=self.attempts.get_state(effect_id))

    def _run(self, session, effect_id, request_id, capability):
        checked_identifier(effect_id)
        checked_identifier(request_id)
        replay = self._replay(effect_id, request_id, capability)
        if replay is not None:
            return replay
        intent, spec, projection = self._prepare(effect_id)
        metadata = self.authorization.issue(session, intent, request_id, capability)
        try:
            return self._dispatch(intent, spec, projection, request_id, capability, metadata)
        finally:
            self.authorization.revoke(metadata["grant_id"])

    def _dispatch(self, intent, spec, projection, request_id, capability, metadata):
        effect_id = intent["effect_id"]
        claim = self.attempts.claim if capability == "graph_write" else self.attempts.claim_reconciliation
        accepted = claim(effect_id, request_id, metadata)
        try:
            self.authorization.bind_attempt(metadata, accepted["attempt_id"], accepted["generation"])
        except BaseException:
            if capability == "graph_write":
                self.attempts.block_authorization(effect_id, accepted["attempt_id"], accepted["generation"])
            else:
                self.attempts.finish_reconciliation_unknown(effect_id, accepted["attempt_id"], accepted["generation"])
            raise
        expected = {}

        def operation(config, current_intent):
            if canonical_json(current_intent) != canonical_json(intent):
                raise ValueError("Publication execution intent conflict")
            config = checked_frozen_config(config, intent["target_profile"])
            target = intent["target_profile"]
            if self.authorization.profile_metadata(target["profile_id"]) != target:
                raise ValueError("Authorized connection frozen profile conflict")
            expected.update(expected_receipt(intent, projection, config))
            return transport_once(
                intent,
                spec,
                projection,
                config,
                capability,
                driver_factory=self.driver_factory,
                transport=self.transport,
            )

        def comparator(current_intent, receipt):
            return canonical_json(current_intent) == canonical_json(intent) and canonical_json(
                receipt
            ) == canonical_json(expected)

        execute = self.attempts.execute_write if capability == "graph_write" else self.attempts.execute_reconciliation
        try:
            execute(
                effect_id,
                accepted["attempt_id"],
                accepted["generation"],
                grant_metadata=metadata,
                operation=operation,
                comparator=comparator,
            )
        except BaseException:
            # Core closes transport failures; also close a read denied before release.
            if capability == "graph_read":
                self.attempts.finish_reconciliation_unknown(effect_id, accepted["attempt_id"], accepted["generation"])
            raise
        return dict(accepted=accepted, state=self.attempts.get_state(effect_id))

    _envelope = staticmethod(receipt_envelope)
