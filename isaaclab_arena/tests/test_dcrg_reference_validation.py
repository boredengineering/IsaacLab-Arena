# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

import importlib
import importlib.util
import numpy as np

import pytest

MODULE = "isaaclab_arena.agentic_environment_generation.dcrg.reference_validation"


def _api(name):
    assert importlib.util.find_spec(MODULE) is not None, "Reference validation module is missing"
    module = importlib.import_module(MODULE)
    assert hasattr(module, name), f"Missing API: {name}"
    return getattr(module, name)


def _trajectory():
    return {
        "poses": np.array([[0, 0, 0, 1, 0, 0, 0], [1, 2, 3, 1, 0, 0, 0]], dtype=float),
        "timestamps": np.array([0.0, 0.02]),
        "frame_id": "world/apple_root",
        "quaternion_order": "wxyz",
    }


def test_quaternion_sign_equivalence():
    reference, actual = _trajectory(), _trajectory()
    actual["poses"][:, 3:] *= -1
    result = _api("compare_pose_trajectory")(reference, actual, 0.001, 0.001)
    assert result["passed"] is True
    assert result["valid_input"] is True
    assert result["sample_count"] == 2
    assert result["max_position_error_m"] == 0.0
    assert result["max_orientation_error_rad"] == 0.0


@pytest.mark.parametrize(
    "defect",
    [
        "length",
        "empty",
        "shape",
        "nan",
        "inf",
        "zero_quaternion",
        "scaled_quaternion",
        "frame",
        "missing_frame",
        "missing_poses",
        "ragged",
        "time_length",
        "time_offset",
        "time_order",
        "time_nan",
        "missing_time",
        "negative_tolerance",
        "nan_tolerance",
        "infinite_tolerance",
        "nonscalar_tolerance",
    ],
)
def test_invalid_input_fails_closed(defect):
    reference, actual = _trajectory(), _trajectory()
    pos_tol, ori_tol = 0.01, 0.01
    if defect == "length":
        actual["poses"] = actual["poses"][:1]
    elif defect == "empty":
        reference["poses"] = actual["poses"] = np.empty((0, 7))
    elif defect == "shape":
        actual["poses"] = np.zeros((2, 8))
    elif defect in ("nan", "inf"):
        actual["poses"][0, 0] = float(defect)
    elif defect == "zero_quaternion":
        actual["poses"][0, 3:] = 0
    elif defect == "scaled_quaternion":
        actual["poses"][0, 3:] *= 2
    elif defect == "frame":
        actual["frame_id"] = "robot/apple_root"
    elif defect == "missing_frame":
        del actual["frame_id"]
    elif defect == "missing_poses":
        del actual["poses"]
    elif defect == "ragged":
        actual["poses"] = [[1], [2, 3]]
    elif defect == "time_length":
        actual["timestamps"] = [0]
    elif defect == "time_offset":
        actual["timestamps"] += 0.01
    elif defect == "time_order":
        reference["timestamps"] = actual["timestamps"] = [0, 0]
    elif defect == "time_nan":
        actual["timestamps"][1] = np.nan
    elif defect == "missing_time":
        del actual["timestamps"]
    elif defect == "negative_tolerance":
        pos_tol = -1
    elif defect == "nan_tolerance":
        ori_tol = np.nan
    elif defect == "infinite_tolerance":
        pos_tol = np.inf
    elif defect == "nonscalar_tolerance":
        pos_tol = [0.01, 0.01]
    result = _api("compare_pose_trajectory")(reference, actual, pos_tol, ori_tol)
    assert result["passed"] is False
    assert result["valid_input"] is False
    assert result["reason"]
    assert result["sample_count"] == 0
    assert result["max_position_error_m"] is None
    assert result["max_orientation_error_rad"] is None


@pytest.mark.parametrize("side", ["reference", "actual"])
@pytest.mark.parametrize("field", ["poses", "timestamps"])
@pytest.mark.parametrize("imaginary", [0.0, 1.0, np.nan, np.inf])
def test_complex_trajectory_input_fails_closed(side, field, imaginary):
    reference, actual = _trajectory(), _trajectory()
    trajectory = reference if side == "reference" else actual
    values = trajectory[field].astype(complex)
    values.flat[0] = complex(values.flat[0].real, imaginary)
    trajectory[field] = values

    result = _api("compare_pose_trajectory")(reference, actual, 0.01, 0.01)

    assert result == {
        "passed": False,
        "valid_input": False,
        "reason": f"{field.capitalize()} must be real-valued",
        "sample_count": 0,
        "max_position_error_m": None,
        "max_orientation_error_rad": None,
    }


@pytest.mark.parametrize("side", ["reference", "actual"])
@pytest.mark.parametrize("field, index", [("poses", 0), ("poses", 4), ("timestamps", 0)])
@pytest.mark.parametrize("scalar_type", [complex, np.complex64, np.complex128])
@pytest.mark.parametrize("imaginary", [0.0, 1.0, np.nan, np.inf])
def test_boxed_complex_trajectory_input_fails_closed(side, field, index, scalar_type, imaginary):
    reference, actual = _trajectory(), _trajectory()
    trajectory = reference if side == "reference" else actual
    values = trajectory[field].astype(object)
    values.flat[index] = scalar_type(complex(values.flat[index], imaginary))
    trajectory[field] = values

    result = _api("compare_pose_trajectory")(reference, actual, 0.01, 0.01)

    assert result == {
        "passed": False,
        "valid_input": False,
        "reason": f"{field.capitalize()} must be real-valued",
        "sample_count": 0,
        "max_position_error_m": None,
        "max_orientation_error_rad": None,
    }


@pytest.mark.parametrize("side", ["reference", "actual"])
@pytest.mark.parametrize("field", ["poses", "timestamps"])
@pytest.mark.parametrize("dtype", [object, "U", "S", bool, "datetime64[s]", "timedelta64[s]"])
def test_non_real_numeric_trajectory_dtype_fails_closed(side, field, dtype):
    reference, actual = _trajectory(), _trajectory()
    trajectory = reference if side == "reference" else actual
    trajectory[field] = trajectory[field].astype(dtype)

    result = _api("compare_pose_trajectory")(reference, actual, 0.01, 0.01)

    assert result == {
        "passed": False,
        "valid_input": False,
        "reason": f"{field.capitalize()} must be real-valued",
        "sample_count": 0,
        "max_position_error_m": None,
        "max_orientation_error_rad": None,
    }


@pytest.mark.parametrize("dtype", [np.int32, np.int64, np.uint32, np.uint64, np.float16, np.float32, np.float64])
@pytest.mark.parametrize("as_list", [False, True])
def test_real_numeric_trajectory_dtypes_are_supported(dtype, as_list):
    reference, actual = _trajectory(), _trajectory()
    for trajectory in (reference, actual):
        trajectory["timestamps"] = np.array([0, 1])
        for field in ("poses", "timestamps"):
            values = trajectory[field].astype(dtype)
            trajectory[field] = values.tolist() if as_list else values

    result = _api("compare_pose_trajectory")(reference, actual, 0.0, 0.0)

    assert result["valid_input"] is True
    assert result["passed"] is True
    assert result["sample_count"] == 2
    assert result["max_position_error_m"] == 0.0
    assert result["max_orientation_error_rad"] == 0.0


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("as_array", [False, True])
@pytest.mark.parametrize("imaginary", [0.0, 1.0, np.nan, np.inf])
def test_complex_tolerance_fails_closed(index, as_array, imaginary):
    tolerances: list[object] = [0.01, 0.01]
    value = np.complex128(complex(0.01, imaginary))
    tolerances[index] = np.asarray(value) if as_array else value

    result = _api("compare_pose_trajectory")(_trajectory(), _trajectory(), *tolerances)

    assert result == {
        "passed": False,
        "valid_input": False,
        "reason": "Tolerances must be real-valued",
        "sample_count": 0,
        "max_position_error_m": None,
        "max_orientation_error_rad": None,
    }


@pytest.mark.parametrize("order", [None, "unknown", "xyzw"])
def test_missing_or_mismatched_quaternion_convention_is_invalid(order):
    reference, actual = _trajectory(), _trajectory()
    if order is None:
        del actual["quaternion_order"]
    else:
        actual["quaternion_order"] = order
    result = _api("compare_pose_trajectory")(reference, actual, 0.01, 0.01)
    assert result["passed"] is False
    assert result["valid_input"] is False


def test_hdf5_inspection_reports_schema_not_success(tmp_path):
    import h5py

    path = tmp_path / "reference.hdf5"
    with h5py.File(path, "w") as file:
        file.attrs["format_version"] = 1
        data = file.create_group("data")
        data.attrs["env_args"] = '{"env_name": ""}'
        episode = data.create_group("demo_0")
        episode.attrs["success"] = True
        episode.attrs["num_samples"] = 2
        episode.create_dataset("actions", shape=(2, 23), dtype="f4")
        episode.create_dataset("processed_actions", shape=(2, 43), dtype="f4")
        for prefix, length in (("states", 2), ("initial_state", 1)):
            episode.create_dataset(f"{prefix}/articulation/robot/root_pose", shape=(length, 7), dtype="f4")
            episode.create_dataset(f"{prefix}/rigid_object/apple/root_pose", shape=(length, 7), dtype="f4")
        episode.create_dataset("camera_obs/rgb", shape=(2, 4, 4, 3), dtype="u1")
    result = _api("inspect_reference_episode")(path, "demo_0")
    assert result["episode_name"] == "demo_0"
    assert result["action_dimension"] == 23
    assert result["processed_action_dimension"] == 43
    assert result["sample_count"] == 2
    assert result["datasets"]["actions"] == {"shape": [2, 23], "dtype": "float32", "attributes": {}}
    assert result["attributes"]["file"]["format_version"] == 1
    assert result["attributes"]["data"]["env_args"] == '{"env_name": ""}'
    assert result["historical_success"] is True
    assert result["success_certified"] is False
    assert result["replay_validated"] is False
    assert result["state_presence"] == {
        "robot_trajectory": True,
        "object_trajectory": True,
        "robot_initial": True,
        "object_initial": True,
    }
    assert result["timestamp_datasets"] == []
    assert result["quaternion_order"] is None
    assert result["runtime_joint_mapping"] is None
    assert result["issues"]


@pytest.mark.parametrize("order", ["wxyz", "xyzw"])
@pytest.mark.parametrize("angle", [0.0, 1e-9, 0.3, np.pi])
def test_hard_bounds_measure_euclidean_and_shortest_angle_errors(order, angle):
    reference, actual = _trajectory(), _trajectory()
    actual["poses"][1, :3] += [0.03, 0.04, 0]
    actual["poses"][1, 3:] = [np.cos(angle / 2), 0, 0, np.sin(angle / 2)]
    if order == "xyzw":
        for trajectory in (reference, actual):
            trajectory["quaternion_order"] = order
            trajectory["poses"][:, 3:] = trajectory["poses"][:, [4, 5, 6, 3]]
    result = _api("compare_pose_trajectory")(reference, actual, 0.01, 1e-10)
    assert result["valid_input"] is True
    assert result["passed"] is False
    assert result["reason"] == "tolerance_exceeded"
    assert result["max_position_error_m"] == pytest.approx(0.05)
    assert result["max_orientation_error_rad"] == pytest.approx(angle, rel=1e-8, abs=1e-12)


@pytest.mark.parametrize("order", ["wxyz", "xyzw"])
@pytest.mark.parametrize("sign", [1, -1])
def test_tiny_quaternion_chord_does_not_false_pass_zero_tolerance(order, sign):
    reference, actual = _trajectory(), _trajectory()
    actual["poses"][0, 3:] = [1, 1e-200, 0, 0]
    actual["poses"][:, 3:] *= sign
    if order == "xyzw":
        for trajectory in (reference, actual):
            trajectory["quaternion_order"] = order
            trajectory["poses"][:, 3:] = trajectory["poses"][:, [4, 5, 6, 3]]

    compare = _api("compare_pose_trajectory")
    result = compare(reference, actual, 0.0, 0.0)

    assert result["passed"] is False
    assert result["valid_input"] is True
    assert result["reason"] == "tolerance_exceeded"
    assert result["sample_count"] == 2
    assert result["max_position_error_m"] == 0.0
    assert result["max_orientation_error_rad"] == pytest.approx(2e-200, rel=1e-14, abs=0.0)
    assert compare(reference, actual, 0.0, 3e-200)["passed"] is True


@pytest.mark.parametrize("order", ["wxyz", "xyzw"])
@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("side", ["reference", "actual"])
@pytest.mark.parametrize(
    "chord",
    [
        0.0,
        np.nextafter(0.0, 1.0),
        2 * np.nextafter(0.0, 1.0),
        3 * np.nextafter(0.0, 1.0),
        5 * np.nextafter(0.0, 1.0),
        np.ldexp(1.0, -1060),
        np.finfo(float).tiny / 2,
        np.finfo(float).tiny,
        1e-300,
        1e-200,
    ],
)
def test_subnormal_quaternion_chord_preserves_positive_angle(order, sign, side, chord):
    reference, actual = _trajectory(), _trajectory()
    perturbed = reference if side == "reference" else actual
    perturbed["poses"][0, 3:] = [1, chord, 0, 0]
    actual["poses"][:, 3:] *= sign
    if order == "xyzw":
        for trajectory in (reference, actual):
            trajectory["quaternion_order"] = order
            trajectory["poses"][:, 3:] = trajectory["poses"][:, [4, 5, 6, 3]]

    compare = _api("compare_pose_trajectory")
    result = compare(reference, actual, 0.0, 0.0)

    assert result["valid_input"] is True
    assert result["sample_count"] == 2
    assert result["max_position_error_m"] == 0.0
    if chord == 0.0:
        assert result["passed"] is True
        assert result["reason"] is None
        assert result["max_orientation_error_rad"] == 0.0
    else:
        assert result["passed"] is False
        assert result["reason"] == "tolerance_exceeded"
        # theta >= 2 * chord; allow subnormal rounding in atan2 before scaling.
        assert 0.0 < 2 * chord <= result["max_orientation_error_rad"] <= 4 * chord
        assert compare(reference, actual, 0.0, chord)["passed"] is False
        assert compare(reference, actual, 0.0, 4 * chord)["passed"] is True
        assert compare(reference, actual, 0.0, result["max_orientation_error_rad"])["passed"] is True


def test_nonfinite_computed_error_fails_closed():
    reference, actual = _trajectory(), _trajectory()
    reference["poses"][0, 0] = 1e308
    actual["poses"][0, 0] = -1e308
    with np.errstate(all="raise"):
        result = _api("compare_pose_trajectory")(reference, actual, 1.0, 1.0)
    assert result["passed"] is False
    assert result["valid_input"] is False
    assert result["max_position_error_m"] is None


@pytest.mark.parametrize("episode_name", ["/data/demo_0", "", "data/demo_0"])
def test_inspection_requires_exact_episode_child_name(tmp_path, episode_name):
    import h5py

    path = tmp_path / "reference.hdf5"
    with h5py.File(path, "w") as file:
        file.create_group("data/demo_0")
    with pytest.raises(ValueError, match="child name"):
        _api("inspect_reference_episode")(path, episode_name)


@pytest.mark.parametrize("defect", ["data_dataset", "episode_dataset"])
def test_inspection_rejects_nongroup_schema(tmp_path, defect):
    import h5py

    path = tmp_path / "reference.hdf5"
    with h5py.File(path, "w") as file:
        file.create_dataset("data" if defect == "data_dataset" else "data/demo_0", data=[0])
    with pytest.raises(ValueError, match="group"):
        _api("inspect_reference_episode")(path, "demo_0")


def test_inspection_flags_metadata_alignment_defects(tmp_path):
    import h5py

    path = tmp_path / "reference.hdf5"
    with h5py.File(path, "w") as file:
        episode = file.create_group("data/demo_0")
        episode.attrs["num_samples"] = 3
        episode.create_dataset("actions", shape=(2, 23), dtype="f4")
        episode.create_dataset("processed_actions", shape=(1, 43), dtype="f4")
        episode.create_dataset("states/articulation/robot/root_pose", shape=(1, 7), dtype="f4")
    result = _api("inspect_reference_episode")(path, "demo_0")
    assert "num_samples does not match actions" in result["issues"]
    assert "Sample count mismatch: processed_actions" in result["issues"]
    assert "Sample count mismatch: states/articulation/robot/root_pose" in result["issues"]
    assert "Missing root-pose data: object_trajectory" in result["issues"]
    assert "Missing root-pose data: robot_initial" in result["issues"]
    assert result["historical_success"] is None
    assert result["success_certified"] is False


def test_inspection_does_not_read_payloads_or_coerce_success_labels(tmp_path):
    import h5py

    path = tmp_path / "metadata_only.hdf5"
    with h5py.File(path, "w") as file:
        episode = file.create_group("data/demo_0")
        episode.attrs["success"] = "false"
        episode.create_dataset(
            "actions",
            shape=(2, 23),
            dtype="f4",
            external=[(str(tmp_path / "absent_payload.bin"), 0, h5py.h5f.UNLIMITED)],
        )
        episode.create_dataset("timestamps", data=[0, 0.02])
        episode.create_dataset("states/rigid_object/apple/root_pose", shape=(0, 7), dtype="f4")
    result = _api("inspect_reference_episode")(path, "demo_0")
    assert result["action_dimension"] == 23
    assert result["historical_success"] == "false"
    assert result["success_certified"] is False
    assert result["timestamp_datasets"] == ["timestamps"]
    assert result["state_presence"]["object_trajectory"] is False
    with h5py.File(path, "r") as file:
        actions = file["data/demo_0/actions"]
        assert isinstance(actions, h5py.Dataset)
        with pytest.raises(OSError):
            actions[()]


def test_import_does_not_load_hdf5_or_simulator():
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            f"import {MODULE}; import sys; assert not {{'h5py', 'torch', 'isaacsim', 'omni'}} & set(sys.modules)",
        ],
        check=True,
    )


def test_missing_file_or_episode_never_returns_a_report(tmp_path):
    import h5py

    inspect = _api("inspect_reference_episode")
    path = tmp_path / "reference.hdf5"
    with pytest.raises(OSError):
        inspect(path, "demo_0")
    with h5py.File(path, "w") as file:
        file.create_group("data")
    with pytest.raises(KeyError):
        inspect(path, "demo_0")


def test_huge_quaternion_is_invalid_without_numeric_warning():
    reference, actual = _trajectory(), _trajectory()
    actual["poses"][0, 3] = 1e308
    with np.errstate(all="raise"):
        result = _api("compare_pose_trajectory")(reference, actual, 0.01, 0.01)
    assert result["valid_input"] is False
    assert result["passed"] is False


def test_orientation_bound_alone_can_reject_matching_positions():
    reference, actual = _trajectory(), _trajectory()
    actual["poses"][0, 3:] = [0, 1, 0, 0]
    result = _api("compare_pose_trajectory")(reference, actual, 0.0, 0.1)
    assert result["valid_input"] is True
    assert result["passed"] is False
    assert result["max_position_error_m"] == 0.0
    assert result["max_orientation_error_rad"] == pytest.approx(np.pi)


def test_position_bound_is_inclusive_without_mutating_input():
    reference, actual = _trajectory(), _trajectory()
    actual["poses"][0, 0] = 0.125
    saved = actual["poses"].copy()
    result = _api("compare_pose_trajectory")(reference, actual, 0.125, 0.0)
    assert result["passed"] is True
    np.testing.assert_array_equal(actual["poses"], saved)
