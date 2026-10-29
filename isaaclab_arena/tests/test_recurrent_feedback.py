# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure recurrent evidence reduction and transactional graph contracts; no live database."""

import pytest

from isaaclab_arena.agentic_environment_generation import lpg_neo4j_sync as sync

BODY = "left_hand_middle_1_link"


def _row(episodes, distances, dx, **extra):
    return {
        "episode": episodes,
        "hand_body": BODY,
        "hand_frame_mode": "pinned",
        "hand_dist_to_obj": distances,
        "hand_x_minus_obj": dx,
        "hand_y_minus_obj": [0.0] * len(episodes),
        "hand_z_minus_obj": [0.0] * len(episodes),
        **extra,
    }


def test_async_environments_have_independent_closest_samples():
    rows = [
        _row([0, 0], [0.3, 0.2], [0.3, -0.2]),
        _row([1, 0], [0.4, 0.1], [0.4, -0.1]),
        _row([1, 1], [0.2, 0.5], [0.2, -0.5]),
    ]
    result = sync.reduce_recurrent_feedback(rows, hand_body_name=BODY)
    assert [(r["env_id"], r["episode"]) for r in result["episodes"]] == [(0, 0), (0, 1), (1, 0), (1, 1)]
    assert [r["dx"] for r in result["episodes"]] == pytest.approx([0.3, 0.2, -0.1, -0.5])
    assert result["dx_mean"] == pytest.approx(-0.025)
    assert result["trace_episode_count"] == 4
    assert result["residual_episode_count"] == 4


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), "0.1", True])
def test_missing_or_nonfinite_residuals_are_not_closest_evidence(bad):
    rows = [_row([0], [0.01], [bad]), _row([0], [0.2], [0.2])]
    result = sync.reduce_recurrent_feedback(rows, hand_body_name=BODY)
    assert result["dx_mean"] == pytest.approx(0.2)
    assert result["episodes"][0]["invalid_residual_samples"] == 1
    assert result["force_max"] is None


@pytest.mark.parametrize(
    "change", [{"hand_body": None}, {"hand_body": "right_hand"}, {"hand_frame_mode": "nearest_of_matching"}]
)
def test_rejects_unpinned_or_wrong_body_frame(change):
    with pytest.raises(ValueError, match="pinned"):
        sync.reduce_recurrent_feedback([{**_row([0], [0.1], [0.1]), **change}], hand_body_name=BODY)


def test_empty_or_entirely_missing_evidence_remains_unknown():
    result = sync.reduce_recurrent_feedback([], hand_body_name=BODY)
    assert result["dx_mean"] is None
    assert result["force_max"] is None
    assert result["trace_episode_count"] == 0
    result = sync.reduce_recurrent_feedback([_row([0], [None], [None])], hand_body_name=BODY)
    assert result["dx_mean"] is None
    assert result["residual_episode_count"] == 0


def test_scalar_rows_keep_explicit_environment_identity():
    row = {key: value[0] if isinstance(value, list) else value for key, value in _row([7], [0.1], [0.1]).items()}
    row["env_id"] = 9
    result = sync.reduce_recurrent_feedback([row], hand_body_name=BODY)
    assert (result["episodes"][0]["env_id"], result["episodes"][0]["episode"]) == (9, 7)


@pytest.mark.parametrize(
    "change", [{"hand_y_minus_obj": []}, {"episode": [True]}, {"env_id": [3, 4]}, {"hand_dist_to_obj": 0.1}]
)
def test_rejects_malformed_batched_shape_or_identity(change):
    with pytest.raises(ValueError):
        sync.reduce_recurrent_feedback([{**_row([0], [0.1], [0.1]), **change}], hand_body_name=BODY)


def _completed(env_id, episode, success, lifted):
    return {
        "env_id": env_id,
        "episode_in_env": episode,
        "success": success,
        "seed": 42,
        "progress": {"objectives": {"lift": {"is_complete": lifted}}},
    }


def test_canonical_scores_use_completed_predicates_not_peak_or_contact():
    rows = [
        _row([0, 0], [0.1, 0.2], [0.1, -0.2], lift=[0.1, 0.1], contact_force=[10.0, 0.0]),
        _row([0, 0], [0.2, 0.3], [0.2, -0.3], lift=[0.0, 0.1]),
        _row([1, 1], [0.001, 0.001], [99.0, 99.0], lift=[0.5, 0.5]),
    ]
    completed = [_completed(0, 0, False, False), _completed(1, 0, True, True)]
    result = sync.reduce_recurrent_feedback(rows, completed, hand_body_name=BODY)
    assert result["lift_rate"] == 0.5
    assert result["success_rate"] == 0.5
    assert result["completed_episode_count"] == 2
    assert result["trace_episode_count"] == 4
    assert result["uncompleted_trace_episode_count"] == 2
    assert result["dx_mean"] == pytest.approx(-0.05)
    assert result["peak_excursion"] == 0.1
    assert result["force_max"] == 10.0
    assert result["contact_channel"] == "unspecified_sensor_force"
    assert "grasp_rate" not in result
    assert [r["seed"] for r in result["episodes"]] == [42, 42]


def test_trace_only_cannot_claim_canonical_scores():
    result = sync.reduce_recurrent_feedback([_row([0], [0.1], [0.1], lift=[0.5])], hand_body_name=BODY)
    assert result["lift_rate"] is None
    assert result["success_rate"] is None
    assert result["completed_episode_count"] == 0
    assert result["peak_excursion"] == 0.5


def test_c1_sequence_lift_comes_from_completed_event_not_whole_task():
    records = [
        {
            "env_id": 0,
            "episode_in_env": 0,
            "seed": 42,
            "success": False,
            "progress": {
                "objectives": {"pick_and_place": {"is_complete": False}},
                "events": [{"predicate_name": "object_lifted_above_resting_min(distance=0.015, min_airborne_steps=5)"}],
            },
        },
        {"env_id": 0, "episode_in_env": 1, "seed": 42, "success": False, "progress": {"events": []}},
    ]
    rows = [_row([0], [0.1], [0.1]), _row([1], [0.1], [0.1])]
    result = sync.reduce_recurrent_feedback(rows, records, hand_body_name=BODY)
    assert result["lift_rate"] == 0.5
    assert result["success_rate"] == 0.0


def test_missing_completed_measurements_do_not_shrink_score_denominator():
    results = [_completed(0, 0, True, True), _completed(1, 0, None, None)]
    result = sync.reduce_recurrent_feedback([_row([0], [0.1], [0.1])], results, hand_body_name=BODY)
    assert result["completed_episode_count"] == 2
    assert result["missing_trace_episode_count"] == 1
    assert result["success_rate"] is None
    assert result["lift_rate"] is None
    assert result["success_observed_count"] == 1
    assert result["lift_observed_count"] == 1


@pytest.mark.parametrize(
    "results",
    [
        [_completed(0, 0, False, False)] * 2,
        [_completed(0, 0, "false", False)],
        [_completed(0, 0, False, 1)],
        [{**_completed(0, 0, False, False), "completed": False}],
    ],
)
def test_rejects_ambiguous_or_unfinished_episode_records(results):
    with pytest.raises(ValueError):
        sync.reduce_recurrent_feedback([_row([0], [0.1], [0.1])], results, hand_body_name=BODY)


class _Result:
    def __init__(self, records):
        self.records = records

    def __iter__(self):
        return iter(self.records)

    def consume(self):
        return None


class _Transaction:
    """Contract fake: database responses only; production code supplies all queries and payloads."""

    def __init__(self, target_count=1, corrupt=False, run=None):
        self.run_record = run if run is not None else {"num_episodes": 1, "success_rate": 0.0}
        self.target_count = target_count
        self.corrupt = corrupt
        self.calls = []
        self.properties = None

    def run(self, query, **parameters):
        self.calls.append((query, parameters))
        if "SET f" in query:
            if self.properties is None or "ON CREATE SET" not in query:
                self.properties = dict(parameters["properties"])
                self.properties["timestamp"] = parameters["ts"] or "2026-09-07T00:00:00Z"
            return _Result([])
        if "properties(f)" in query:
            properties = dict(self.properties)
            if self.corrupt:
                properties["cartesian_dx"] = 99.0
            return _Result([{
                "feedback": properties,
                "timestamp_matches": parameters.get("ts") is None or parameters["ts"] == properties["timestamp"],
            }])
        return _Result([self.run_record] * self.target_count)


class _Driver:
    def __init__(self, **kwargs):
        self.tx = _Transaction(**kwargs)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute_write(self, callback):
        before = dict(self.tx.properties) if self.tx.properties is not None else None
        try:
            result = callback(self.tx)
        except Exception:
            self.tx.properties = before
            self.rolled_back = True
            raise
        self.committed = True
        return result

    def close(self):
        self.closed = True


def _sync_args(tmp_path):
    import json

    traces = tmp_path / "trace.jsonl"
    traces.write_text(json.dumps(_row([0], [0.1], [0.1], lift=[0.2])) + "\n")
    results = tmp_path / "episode_results.jsonl"
    results.write_text(json.dumps(_completed(0, 0, False, False)) + "\n")
    return dict(
        eval_id="eval-existing",
        env_name="scene",
        reach_traces_path=str(traces),
        episode_results_path=str(results),
        env_version="v32",
        reifier_id="apple_on_table",
        hand_body_name=BODY,
    )


def _registered_run(tmp_path):
    import hashlib
    import json
    from pathlib import Path

    if not (tmp_path / "trace.jsonl").exists():
        _sync_args(tmp_path)
    paths = sorted(str(tmp_path / name) for name in ("trace.jsonl", "episode_results.jsonl"))
    return {
        "num_episodes": 1,
        "success_rate": 0.0,
        "artifact_paths": paths,
        "artifact_sha256": [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths],
        "episode_results_json": json.dumps([_completed(0, 0, False, False)], sort_keys=True, separators=(",", ":")),
    }


@pytest.mark.parametrize("artifact", ["reach_traces_path", "episode_results_path", "raw_records", "legacy"])
def test_registered_evidence_cannot_change_with_same_counts_and_rates(tmp_path, artifact):
    import json
    from pathlib import Path

    arguments = _sync_args(tmp_path)
    driver = _Driver(run=_registered_run(tmp_path))
    sync.sync_recurrent_feedback_to_neo4j(**arguments, driver=driver)
    original = dict(driver.tx.properties)
    if artifact == "legacy":
        del driver.tx.run_record["artifact_paths"]
    elif artifact == "raw_records":
        driver.tx.run_record["episode_results_json"] = json.dumps([_completed(0, 0, False, True)])
    else:
        path = Path(arguments[artifact])
        row = json.loads(path.read_text())
        row["hand_x_minus_obj" if artifact == "reach_traces_path" else "seed"] = (
            [0.2] if artifact == "reach_traces_path" else 7
        )
        path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="provenance|evidence"):
        sync.sync_recurrent_feedback_to_neo4j(**arguments, driver=driver)
    assert driver.rolled_back
    assert driver.tx.properties == original


def test_feedback_write_targets_existing_identity_and_verifies_before_commit(tmp_path):
    driver = _Driver(run=_registered_run(tmp_path))
    result = sync.sync_recurrent_feedback_to_neo4j(**_sync_args(tmp_path), driver=driver)
    assert driver.committed and not driver.closed
    assert result["verified"] is True
    assert result["lift_rate"] == 0.0
    assert result["env_version"] == "v32"
    assert result["reifier_id"] == "apple_on_table"
    assert len(driver.tx.calls) == 3
    for query, parameters in driver.tx.calls:
        assert "EVALUATED_GRAPH" in query
        assert "HAS_REIFIER" in query
        assert "$env_version" in query and "$reifier_id" in query
        assert parameters["eval_id"] == "eval-existing"
        assert parameters["env_name"] == "scene"
        assert parameters["env_version"] == "v32"
        assert parameters["reifier_id"] == "apple_on_table"
        assert "MERGE (ev:" not in query
        assert "MERGE (env:" not in query
    write = driver.tx.calls[1][0]
    assert "MERGE (ev)-[f:FEEDBACK_MUTATION]->(rf)" in write
    assert "SET ev." not in write  # Per-target residuals must not clobber run-wide scores.
    assert "properties(f)" in driver.tx.calls[-1][0]
    assert driver.tx.properties["episode_results_path"].endswith("episode_results.jsonl")
    assert driver.tx.properties["hand_body"] == BODY


@pytest.mark.parametrize("target_count", [0, 2])
def test_missing_or_ambiguous_graph_identity_rejected_before_write(tmp_path, target_count):
    driver = _Driver(target_count=target_count, run=_registered_run(tmp_path))
    with pytest.raises(ValueError, match="target"):
        sync.sync_recurrent_feedback_to_neo4j(**_sync_args(tmp_path), driver=driver)
    assert driver.rolled_back and not driver.committed
    assert len(driver.tx.calls) == 1
    assert driver.tx.properties is None


def test_bad_readback_rolls_back_the_feedback_edge(tmp_path):
    driver = _Driver(corrupt=True, run=_registered_run(tmp_path))
    with pytest.raises(RuntimeError, match="verification"):
        sync.sync_recurrent_feedback_to_neo4j(**_sync_args(tmp_path), driver=driver)
    assert driver.rolled_back and not driver.committed
    assert driver.tx.properties is None


@pytest.mark.parametrize("field", ["eval_id", "env_name", "env_version", "reifier_id", "hand_body_name"])
def test_missing_explicit_identity_rejected_without_database_access(tmp_path, field):
    arguments = _sync_args(tmp_path)
    arguments[field] = ""
    driver = _Driver(run=_registered_run(tmp_path))
    with pytest.raises(ValueError):
        sync.sync_recurrent_feedback_to_neo4j(**arguments, driver=driver)
    assert not driver.tx.calls


@pytest.mark.parametrize(
    "run",
    [
        {"num_episodes": None, "success_rate": None},
        {"num_episodes": 0, "success_rate": 0.0},
        {"num_episodes": 2, "success_rate": 0.0},
        {"num_episodes": 1, "success_rate": float("nan")},
        {"num_episodes": 1, "success_rate": 1.0},
    ],
)
def test_incomplete_or_conflicting_canonical_run_rejected(tmp_path, run):
    driver = _Driver(run=run)
    with pytest.raises(ValueError, match="evaluation"):
        sync.sync_recurrent_feedback_to_neo4j(**_sync_args(tmp_path), driver=driver)
    assert driver.rolled_back
    assert driver.tx.properties is None


@pytest.mark.parametrize("content", ["", "{}", "[]", "null"])
def test_empty_or_malformed_trace_is_rejected_without_database_access(tmp_path, content):
    from pathlib import Path

    arguments = _sync_args(tmp_path)
    Path(arguments["reach_traces_path"]).write_text(content)
    driver = _Driver(run=_registered_run(tmp_path))
    with pytest.raises(ValueError):
        sync.sync_recurrent_feedback_to_neo4j(**arguments, driver=driver)
    assert not driver.tx.calls


def test_artifact_identity_conflict_rejected_before_database_access(tmp_path):
    import json
    from pathlib import Path

    arguments = _sync_args(tmp_path)
    row = _row([0], [0.1], [0.1], eval_id="other-run")
    Path(arguments["reach_traces_path"]).write_text(json.dumps(row))
    driver = _Driver(run=_registered_run(tmp_path))
    with pytest.raises(ValueError, match="identity"):
        sync.sync_recurrent_feedback_to_neo4j(**arguments, driver=driver)
    assert not driver.tx.calls


def test_feedback_payload_retains_content_hash_and_dispersion(tmp_path):
    import hashlib
    from pathlib import Path

    arguments = _sync_args(tmp_path)
    driver = _Driver(run=_registered_run(tmp_path))
    sync.sync_recurrent_feedback_to_neo4j(**arguments, driver=driver)
    props = driver.tx.properties
    assert props["reach_traces_sha256"] == hashlib.sha256(Path(arguments["reach_traces_path"]).read_bytes()).hexdigest()
    assert (
        props["episode_results_sha256"]
        == hashlib.sha256(Path(arguments["episode_results_path"]).read_bytes()).hexdigest()
    )
    result = sync.reduce_recurrent_feedback([_row([0, 0], [0.1, 0.3], [0.1, 0.3])], hand_body_name=BODY)
    assert result["dx_std"] == pytest.approx(0.1414213562373095)


def test_feedback_target_requires_policy_and_reifier_endpoints(tmp_path):
    driver = _Driver(run=_registered_run(tmp_path))
    sync.sync_recurrent_feedback_to_neo4j(**_sync_args(tmp_path), driver=driver)
    for query, _ in driver.tx.calls:
        assert "USED_POLICY" in query
        assert "REIFIES_SUBJECT" in query
        assert "REIFIES_OBJECT" in query


class _ReadDriver(_Driver):
    def __init__(self):
        super().__init__()
        self.calls = []

    def run(self, query, **parameters):
        self.calls.append((query, parameters))
        return _Result([])


def test_feedback_read_requires_exact_version_and_relation():
    driver = _ReadDriver()
    assert (
        sync.fetch_recurrent_feedback_from_neo4j(
            "scene", eval_id="eval-existing", driver=driver, env_version="v32", reifier_id="apple_on_table"
        )
        is None
    )
    query, parameters = driver.calls[0]
    assert "HAS_REIFIER" in query and "$env_version" in query and "$reifier_id" in query
    assert parameters["env_version"] == "v32"
    assert parameters["reifier_id"] == "apple_on_table"


@pytest.mark.parametrize("kwargs", [{}, {"env_version": "v32"}, {"reifier_id": "apple_on_table"}])
def test_unqualified_feedback_read_is_rejected(kwargs):
    driver = _ReadDriver()
    with pytest.raises(ValueError):
        sync.fetch_recurrent_feedback_from_neo4j("scene", driver=driver, **kwargs)
    assert not driver.calls


@pytest.mark.parametrize("progress", [None, [], {"objectives": None}, {"objectives": {"lift": None}}])
def test_missing_progress_is_unknown_not_a_success_or_exception(progress):
    record = {**_completed(0, 0, False, False), "progress": progress}
    result = sync.reduce_recurrent_feedback([_row([0], [0.1], [0.1])], [record], hand_body_name=BODY)
    assert result["lift_rate"] is None
    assert result["lift_observed_count"] == 0


@pytest.mark.parametrize("record", [None, [], "bad"])
def test_pure_reducer_rejects_nonobject_episode_records(record):
    with pytest.raises(ValueError, match="Episode result"):
        sync.reduce_recurrent_feedback([], [record], hand_body_name=BODY)


def test_repeat_sync_has_stable_evidence_payload_and_merge_identity(tmp_path):
    arguments = _sync_args(tmp_path)
    driver = _Driver(run=_registered_run(tmp_path))
    first = sync.sync_recurrent_feedback_to_neo4j(**arguments, driver=driver)
    properties = dict(driver.tx.properties)
    second = sync.sync_recurrent_feedback_to_neo4j(**arguments, driver=driver)
    assert first == second
    assert properties == driver.tx.properties
    writes = [(query, params) for query, params in driver.tx.calls if "SET f" in query]
    assert len(writes) == 2
    assert all("MERGE (ev)-[f:FEEDBACK_MUTATION]->(rf)" in query for query, _ in writes)
    assert writes[0][1] == writes[1][1]


@pytest.mark.parametrize("change", ["lift_objective", "timestamp", "artifact"])
def test_conflicting_retry_preserves_original_feedback(tmp_path, change):
    from pathlib import Path

    arguments = _sync_args(tmp_path)
    driver = _Driver(run=_registered_run(tmp_path))
    arguments["timestamp"] = "2026-09-07T00:00:00Z"
    sync.sync_recurrent_feedback_to_neo4j(**arguments, driver=driver)
    original = dict(driver.tx.properties)
    if change == "artifact":
        alternative = tmp_path / "alternative.jsonl"
        alternative.write_bytes(Path(arguments["reach_traces_path"]).read_bytes())
        arguments["reach_traces_path"] = str(alternative)
        driver.tx.run_record["artifact_paths"].append(str(alternative))
        driver.tx.run_record["artifact_sha256"].append(original["reach_traces_sha256"])
    else:
        arguments[change] = "other" if change == "lift_objective" else "2026-09-08T00:00:00Z"
    with pytest.raises(RuntimeError, match="verification|conflict"):
        sync.sync_recurrent_feedback_to_neo4j(**arguments, driver=driver)
    assert driver.rolled_back
    assert driver.tx.properties == original


def test_owned_driver_closes_after_readback_failure(tmp_path, monkeypatch):
    driver = _Driver(corrupt=True, run=_registered_run(tmp_path))
    monkeypatch.setattr(sync, "get_neo4j_driver", lambda: driver)
    with pytest.raises(RuntimeError, match="verification"):
        sync.sync_recurrent_feedback_to_neo4j(**_sync_args(tmp_path))
    assert driver.closed
    assert driver.rolled_back
