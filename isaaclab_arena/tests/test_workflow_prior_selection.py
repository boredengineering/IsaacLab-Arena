# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure frozen retrieval intent and retained-prior boundary regressions."""

import ast
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from functools import partial
from pathlib import Path
from types import SimpleNamespace


def retrieval_selection():
    """An explicit test-only source; never a production default."""
    settings = {
        "limit": 2,
        "min_success_rate": 0.0,
        "min_episodes": 1,
        "query_timeout_seconds": 5.0,
        "connection_timeout_seconds": 3.0,
        "connection_acquisition_timeout_seconds": 5.0,
        "max_transaction_retry_time_seconds": 0.0,
    }
    eligibility = "measured-or-structural-v1"
    digest = hashlib.sha256(
        json.dumps({"eligibility": eligibility, "settings": settings}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": "1",
        "source": "neo4j-legacy-graph-rag",
        "credential_alias": "prior",
        "endpoint": "bolt://127.0.0.1:17687",
        "database": "priors",
        "eligibility": eligibility,
        "settings": settings,
        "settings_sha256": digest,
        "required": True,
        "allow_empty": False,
    }


def request(*, retrieval=True):
    from workflow_graphql_execution_join_fixture import contract, registrations

    value = json.loads(contract(registrations()))
    if retrieval:
        value["schema_version"] = "2"
        value["effects"]["allow_database_reads"] = True
        value["retrieval"] = retrieval_selection()
    return value


@contextmanager
def retained_prior(*, status="empty", required=True, allow_empty=False):
    from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest, parse_contract
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts

    value = request()
    value["retrieval"].update(required=required, allow_empty=allow_empty)
    contract = parse_contract(json.dumps(value))
    assert contract.source.kind == "new"
    snapshot = empty_snapshot(
        contract.source.prompt, status=status, warning="unconfigured" if status == "unavailable" else ""
    )
    if status == "empty":
        snapshot["effective_settings"].update(contract.retrieval.settings.model_dump(mode="json"))
        snapshot["timing"] = dict(source="local_monotonic", elapsed_seconds=0.0)
    with tempfile.TemporaryDirectory() as temporary:
        with ArtifactArea.create(Path(temporary) / "area", store_id="test", registry_id="scope") as area:
            artifacts = RetainedPriorArtifacts(area)
            receipt = artifacts.write(
                contract.source.prompt, contract_digest(contract), "run", snapshot, protect=lambda _: None
            )
            raw = artifacts.reference(receipt, contract=contract, run_id="run", protect=lambda _: None)
            yield artifacts, contract, raw, receipt, Path(temporary) / "area"


class PriorSelection(unittest.TestCase):
    def test_joined_setup_fixture_is_not_exposed_by_pytest_source_dump(self):
        import pytest

        root = Path(__file__).resolve().parents[2]
        path = root / "isaaclab_arena/tests/test_environment_workflow_graphql_execution_joined_neo4j.py"
        tree = ast.parse(path.read_text())
        assignments = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "credential" for target in node.targets)
        ]
        expression = ast.unparse(assignments[0].value)
        probe = (
            "import workflow_graphql_execution_join_fixture as fixture\n"
            "operational_credentials = getattr(fixture, 'operational_credentials', None)\n"
            "def test_expected_failure():\n"
            f"    credential = {expression}\n"
            "    assert False, 'deliberate bounded diagnostic failure'\n"
        )
        captured = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            test = Path(temporary) / "test_diagnostic.py"
            test.write_text(probe)
            with redirect_stdout(captured), redirect_stderr(captured):
                code = pytest.main(["--noconftest", "-c", "/dev/null", "-p", "no:cacheprovider", "-q", str(test)])
        self.assertEqual(code, 1)
        self.assertFalse(
            any(value in captured.getvalue() for value in ("synthetic-user", "synthetic-only-secret")),
            "Private fixture constants appeared in pytest diagnostics",
        )

    def test_prior_grant_expiry_vetoes_context_exit(self):
        from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json, parse_contract
        from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import ForegroundAuthority
        from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants

        contract = parse_contract(json.dumps(request()))
        now = [1.0]
        scope = dict(database="operations", deployment_id="dep", workspace_id="workspace")
        run = SimpleNamespace(run_id="run", operation_id="op", contract_json=canonical_json(contract))
        grants = ExecutionGrants(clock=lambda: now[0])
        authority = ForegroundAuthority(
            **scope,
            store=SimpleNamespace(
                database=scope["database"],
                scope={k: v for k, v in scope.items() if k != "database"},
                get_run=lambda _: run,
            ),
            grants=grants,
            clock=lambda: now[0],
            principal_lookup=lambda p: dict(scope, principal=p, expires_at=100.0, revoked=False),
            profiles={},
            current_config=lambda _: None,
            prior_source=lambda _, credentials=False: (
                dict(
                    uri="bolt://127.0.0.1:17687",
                    user="fixture-prior-user",
                    password="fixture-prior-private",
                    database="priors",
                )
                if credentials
                else None
            ),
        )
        with self.assertRaises(ValueError):
            with authority.prior_read("reader", contract, run_id="run", deadline=30.0):
                now[0] = 30.0
        self.assertFalse(grants._records)

    def test_offline_report_declares_prior_support_without_selection_or_authority(self):
        from isaaclab_arena.agentic_environment_generation.workflow.setup_readiness import setup_readiness

        report = setup_readiness()
        self.assertEqual(
            report["installed_boundary"]["prior_retrieval"],
            {
                "mode": "harness_only",
                "workflow_contract_schema": "2",
                "source": "neo4j-legacy-graph-rag",
                "eligibility": "measured-or-structural-v1",
                "continuation": "retained_exact_snapshot_only",
                "managed_source": "unsupported",
            },
        )
        self.assertEqual(report["roles"]["prior_read"]["public_selection"], "unresolved")
        self.assertEqual(report["roles"]["prior_read"]["access"], "not_checked")
        self.assertEqual(report["roles"]["prior_read"]["capability"], "not_checked")
        self.assertFalse(report["execution_authorized"])

    def test_read_expiry_blocks_later_io_and_never_becomes_optional_fallback(self):
        from isaaclab_arena.agentic_environment_generation.workflow.contracts import PriorRetrievalSettings
        from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_access import retrieve_snapshot

        settings = PriorRetrievalSettings.model_validate(retrieval_selection()["settings"])
        config = dict(
            uri="bolt://127.0.0.1:17687", user="fixture-prior-user", password="fixture-prior-private", database="priors"
        )
        for stage in ("before_driver", "short_allowance", "driver", "query", "session_exit", "driver_close", "valid"):
            with self.subTest(stage=stage):
                now = [30.0 if stage == "before_driver" else 29.0 if stage == "short_allowance" else 1.0]
                calls = []

                def check(seconds=0.0):
                    if now[0] + seconds >= 30.0:
                        raise ValueError("Expired test read grant")

                class Session:
                    def __enter__(self):
                        calls.append("session_enter")
                        return self

                    def run(self, *args, **kwargs):
                        calls.append("query")
                        if stage == "query":
                            now[0] = 30.0
                        return iter(())

                    def __exit__(self, *args):
                        calls.append("session_exit")
                        if stage == "session_exit":
                            now[0] = 30.0

                class Driver:
                    def session(self, **kwargs):
                        return Session()

                    def close(self):
                        calls.append("driver_close")
                        if stage == "driver_close":
                            now[0] = 30.0

                def factory(**kwargs):
                    calls.append("driver")
                    if stage == "driver":
                        now[0] = 30.0
                    return Driver()

                invoke = partial(
                    retrieve_snapshot,
                    "fixture table",
                    config,
                    driver_factory=factory,
                    settings=settings,
                    read_guard=check,
                )
                if stage == "valid":
                    self.assertEqual(invoke()["status"], "empty")
                    self.assertEqual(calls.count("query"), 2)
                else:
                    with self.assertRaises(ValueError):
                        invoke()
                if stage in {"before_driver", "short_allowance"}:
                    self.assertFalse(calls)
                else:
                    self.assertEqual(calls.count("driver_close"), 1)
                if stage == "driver":
                    self.assertEqual(calls.count("query"), 0)
                if stage == "query":
                    self.assertEqual(calls.count("query"), 1)

    def test_versioned_selection_survives_canonical_roundtrip(self):
        from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json, parse_contract

        value = request()
        selected = parse_contract(json.dumps(value))
        self.assertEqual(selected.retrieval.model_dump(mode="json"), value["retrieval"])
        self.assertEqual(parse_contract(canonical_json(selected)), selected)
        self.assertEqual(json.loads(canonical_json(selected))["retrieval"], value["retrieval"])

    def test_schema_one_wire_shape_stays_unchanged(self):
        from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json, parse_contract

        value = request(retrieval=False)
        self.assertNotIn("retrieval", value)
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
        self.assertEqual(canonical_json(parse_contract(raw)), raw)

    def test_missing_mismatched_or_unsupported_selections_are_not_defaulted(self):
        from isaaclab_arena.agentic_environment_generation.workflow.contracts import parse_contract

        for field, altered in (
            ("source", "managed"),
            ("endpoint", "bolt://localhost:17687"),
            ("endpoint", "neo4j://127.0.0.1:17687"),
            ("endpoint", "bolt://127.0.0.1:17687/"),
            ("eligibility", "all-records"),
            ("settings_sha256", "0" * 64),
            ("required", 1),
            ("allow_empty", "true"),
        ):
            with self.subTest(field=field, altered=altered):
                value = request()
                value["retrieval"][field] = altered
                with self.assertRaises(ValueError):
                    parse_contract(json.dumps(value))
        for field in retrieval_selection():
            value = request()
            del value["retrieval"][field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                parse_contract(json.dumps(value))
        value = request()
        value["effects"]["allow_database_reads"] = False
        with self.assertRaises(ValueError):
            parse_contract(json.dumps(value))
        value = request(retrieval=False)
        value["retrieval"] = None
        with self.assertRaises(ValueError):
            parse_contract(json.dumps(value))

    def test_required_optional_and_empty_policy_reuses_only_the_retained_outcome(self):
        for status, required, allow_empty, allowed in (
            ("empty", True, False, False),
            ("empty", False, False, False),
            ("empty", True, True, True),
            ("empty", False, True, True),
            ("unavailable", True, True, False),
            ("unavailable", False, False, True),
        ):
            with self.subTest(status=status, required=required, allow_empty=allow_empty):
                with retained_prior(status=status, required=required, allow_empty=allow_empty) as (
                    artifacts,
                    contract,
                    raw,
                    receipt,
                    _,
                ):
                    reopen = partial(artifacts.reopen, contract=contract, run_id="run", protect=lambda _: None)
                    self.assertEqual(reopen(raw, enforce_policy=False), receipt)
                    if allowed:
                        self.assertEqual(reopen(raw), receipt)
                    else:
                        with self.assertRaisesRegex(ValueError, "requirement not satisfied"):
                            reopen(raw)

    def test_restart_refuses_missing_foreign_or_changed_linkage_and_exact_bytes(self):
        with retained_prior(allow_empty=True) as (artifacts, contract, raw, receipt, root):
            reopen = partial(artifacts.reopen, contract=contract, run_id="run", protect=lambda _: None)
            self.assertEqual(reopen(raw), receipt)
            for changed in (
                None,
                "{}",
                " " + raw,
                raw.replace('"run_id":"run"', '"run_id":"foreign"'),
                raw.replace('"disposition":"empty"', '"disposition":"unavailable"'),
            ):
                with self.subTest(changed=changed is None), self.assertRaises(ValueError):
                    reopen(changed)
            path = root / receipt.relative_directory / "prior.json"
            original = path.read_bytes()
            for changed in (b"{}", original + b"\n"):
                try:
                    path.write_bytes(changed)
                    with self.assertRaises(ValueError):
                        reopen(raw)
                finally:
                    path.write_bytes(original)
            self.assertEqual(reopen(raw), receipt)


if __name__ == "__main__":
    unittest.main()
