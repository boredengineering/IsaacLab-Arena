# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Missing measurements cannot imply successful or never-started retrieval."""

import hashlib

import pytest

from isaaclab_arena.agentic_environment_generation.prior_receipt import (
    TEXT_FIELDS,
    SnapshotRejected,
    empty_snapshot,
    format_prior_context,
    validate_prior_snapshot,
)


def test_existing_not_started_and_unavailable_timing_remain_distinct():
    receipt = empty_snapshot("Arrange objects")
    assert validate_prior_snapshot(receipt, prompt="Arrange objects")["timing"]["source"] == "not_started"
    receipt["timing"] = {"source": "unavailable", "elapsed_seconds": None}
    assert validate_prior_snapshot(receipt, prompt="Arrange objects")["timing"] == receipt["timing"]


@pytest.mark.parametrize("status", ["empty", "measured", "structural", "not_requested"])
def test_missing_timing_cannot_attest_another_outcome(status):
    receipt = empty_snapshot("Arrange objects")
    receipt.update(status=status, warnings=[])
    if status != "not_requested":
        receipt["timing"] = {"source": "local_monotonic", "elapsed_seconds": 0.25}
    if status in {"measured", "structural"}:
        prior = dict.fromkeys(TEXT_FIELDS)
        prior.update(
            name="scene",
            objects=[],
            relations=[],
            evidence="measured" if status == "measured" else "unevaluated",
            success_rate=0.5 if status == "measured" else None,
            episodes=1 if status == "measured" else None,
            evaluation_id="run" if status == "measured" else None,
        )
        receipt["priors"] = [prior]
        receipt["exact_context"] = format_prior_context([prior])
        receipt["context_sha256"] = hashlib.sha256(receipt["exact_context"].encode()).hexdigest()
    assert validate_prior_snapshot(receipt, prompt="Arrange objects") == receipt
    receipt["timing"] = {"source": "unavailable", "elapsed_seconds": None}
    with pytest.raises(SnapshotRejected):
        validate_prior_snapshot(receipt, prompt="Arrange objects")


@pytest.mark.parametrize("elapsed", [0, False, 180, float("nan")])
def test_unavailable_timing_cannot_carry_a_numeric_measurement(elapsed):
    receipt = empty_snapshot("Arrange objects")
    receipt["timing"] = {"source": "unavailable", "elapsed_seconds": elapsed}
    with pytest.raises(SnapshotRejected):
        validate_prior_snapshot(receipt, prompt="Arrange objects")
