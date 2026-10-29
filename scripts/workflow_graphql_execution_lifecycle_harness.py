# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Fixed in-process lifecycle cohort; inherited query denials, never SDK/children."""

import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

SELF = "scripts/workflow_graphql_execution_lifecycle_harness.py"
TEST = "isaaclab_arena/tests/test_environment_workflow_execution_lifecycle.py"
SPEC = "outputs/workflow/plan04-implementation/installed-execution/lifecycle-spec.md"
INVENTORY = "outputs/workflow/plan04-implementation/installed-execution/lifecycle-source-files.json"
ARCHIVE = "outputs/workflow/plan04-implementation/installed-execution/correction-round1-preimage/execution_owner.py"
ARCHIVE_SHA256 = "3d1ff06c7ee5ff08df5430cee4784ba9f753375fc1fe17bb366929d98fa31e67"
# Separate measured cohort: 335 repository leaves and four generated leaves.
SOURCE_LIMIT = 339
CASES = (
    "test_execution_server_observation_does_not_cancel_unresolved_cleanup[timeout]",
    "test_execution_server_observation_does_not_cancel_unresolved_cleanup[cleanup_error]",
    "test_execution_stop_precedes_blocked_admission_drain",
    "test_historical_owner_fails_stop_before_blocked_admission_drain",
    "test_execution_cleanup_timeout_is_sticky_and_retains_area",
    "test_execution_stop_while_authenticated_body_and_query_are_pending",
    "test_execution_cleanup_error_is_observable_and_never_releases_area",
)
WITNESS_FILE = "lifecycle-blocked-admission.json"
WITNESSES = {}


def verify_sources():
    """Rehash the exact read-only inventory without importing application code."""
    root = Path("/source")
    assert os.statvfs(root).f_flag & os.ST_RDONLY
    raw = (root / "source-manifest.json").read_bytes()
    assert len(raw) <= 65536
    manifest = json.loads(raw)
    files = json.loads((root / INVENTORY).read_bytes())
    assert type(files) is list and len(files) == len(set(files)) == SOURCE_LIMIT - 4
    assert {SELF, TEST, SPEC, INVENTORY, ARCHIVE, "scripts/workflow_process_harness.py"} <= set(files)
    assert set(manifest) == set(files) | {"closure.json", "graphql-import-check.py", "graphql-profile.json"}
    total = len(raw)
    for name, digest in manifest.items():
        assert type(name) is str and type(digest) is str and re.fullmatch(r"[a-f0-9]{64}", digest)
        parts = Path(name).parts
        assert parts and not Path(name).is_absolute() and ".." not in parts
        path = root
        for part in parts:
            path /= part
            assert not path.is_symlink()
        assert path.is_file() and os.statvfs(path).f_flag & os.ST_RDONLY
        with path.open("rb") as stream:
            data = stream.read(8 * 1024 * 1024 + 1)
        total += len(data)
        assert total <= 8 * 1024 * 1024
        assert hashlib.sha256(data).hexdigest() == digest
    assert manifest[ARCHIVE] == ARCHIVE_SHA256
    return manifest


def historical_owner():
    """Load only the hash-pinned historical owner, with current actual dependencies."""
    verify_sources()
    path = Path("/source") / ARCHIVE
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ARCHIVE_SHA256
    name = "isaaclab_arena.agentic_environment_generation.workflow.api._lifecycle_historical_owner"
    assert name not in sys.modules
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    # No sys.modules substitution of the real owner and no configurable path.
    # Compile the checked bytes rather than reopening through a bytecode loader.
    exec(compile(raw, str(path), "exec"), module.__dict__)
    assert module.ExecutionOwner.__module__ == name
    return module.ExecutionOwner


def begin_tests(guard):
    """Permanently remove even owned-Bolt permission after the driver self-check."""
    assert guard.query_only and not (guard.scene or guard.cli or guard.control)
    assert guard.fixed_spec is None and not guard.children
    assert guard.allowed["child_launch"] == 0 and guard.allowed["bolt"] > 0
    assert not any(guard.forbidden.values())
    before = dict(guard.allowed)
    guard.db_ip = None
    return before


def record_blocked_admission(kind, observation):
    """Retain real observations, never label collection/import failure a RED."""
    assert kind in {"current", "historical"} and kind not in WITNESSES
    assert set(observation) == {"admission_entered", "close_pending", "refused", "area_retained", "stop_before_release", "closed_after_release"}
    assert all(type(value) is bool for value in observation.values())
    WITNESSES[kind] = observation
    Path("/evidence", WITNESS_FILE).write_text(json.dumps({
        "scope": "in-process inert-port behavioral comparison; not installed active-worker shutdown",
        "historical_path": ARCHIVE,
        "historical_sha256": ARCHIVE_SHA256,
        "observations": WITNESSES,
    }, indent=2))


def finish_tests(guard, before, sources):
    """Require both fixed behavioral witnesses and unchanged zero-effect policy."""
    assert guard.db_ip is None and guard.allowed == before
    assert not guard.children and guard.fixed_spec is None
    assert not any(guard.forbidden.values())
    assert not {"openai", "anthropic", "boto3", "isaacsim", "omni", "carb", "pxr", "isaaclab", "torch", "sqlite3", "_sqlite3"}.intersection(sys.modules)
    assert verify_sources() == sources
    assert set(WITNESSES) == {"current", "historical"}
    for kind, observation in WITNESSES.items():
        assert all(value for name, value in observation.items() if name != "stop_before_release")
        assert observation["stop_before_release"] is (kind == "current")
    return dict(lifecycle=dict(
        scope="real ExecutionOwner and in-process ASGI; inert external ports only",
        historical_owner_sha256=ARCHIVE_SHA256,
        blocked_admission=WITNESSES,
        test_effects_denied=True,
        installed_active_worker_shutdown_proven=False,
    ))
