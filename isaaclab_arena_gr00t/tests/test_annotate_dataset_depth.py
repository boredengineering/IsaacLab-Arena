# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the DA3 depth annotation pass."""

import importlib.util
import numpy as np
from pathlib import Path

import pytest

# Loaded by path because ``scripts/`` is not a package, and deliberately so: the annotator is a
# standalone entry point that must run inside the GR00T image without importing Arena.
_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "annotate_dataset_depth.py"
_spec = importlib.util.spec_from_file_location("annotate_dataset_depth", _MODULE_PATH)
annotate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(annotate)


def test_focal_pixels_matches_the_g1_head_camera():
    """The G1 head camera's intrinsics must resolve to its known pixel focal length.

    ``G1CameraCfg.robot_head_cam`` spawns a 15mm lens and Isaac Lab's ``PinholeCameraCfg`` default
    aperture is 20.955mm, so a 640px-wide frame has fx = 458.1px.
    """
    focal = annotate.focal_pixels(15.0, 20.955, 640)

    assert focal == pytest.approx(458.12, abs=0.01)


def test_focal_pixels_scales_with_the_network_input():
    """The focal that belongs in DA3's metric conversion is the focal at the resolution it is fed.

    DA3 resizes to a fixed shorter side, which rescales the focal. Using the native focal instead
    understates the conversion factor, and this is the trap that produced a doubled error in an
    earlier measurement.
    """
    native = annotate.focal_pixels(15.0, 20.955, 640)
    as_fed = annotate.focal_pixels(15.0, 20.955, 640, input_scale=686 / 640)

    assert as_fed > native
    assert as_fed / annotate.DA3_CANONICAL_FOCAL == pytest.approx(1.637, abs=0.005)


def test_focal_pixels_rejects_degenerate_intrinsics():
    """A zero or negative aperture is a configuration error, not something to divide by."""
    with pytest.raises(AssertionError, match="Degenerate intrinsics"):
        annotate.focal_pixels(15.0, 0.0, 640)


def test_quantise_depth_preserves_millimetres():
    """Depth round-trips through uint16 millimetres to within half a millimetre."""
    depth = np.array([[0.0, 0.4630, 0.8695, 2.5370]], dtype=np.float32)

    quantised = annotate.quantise_depth_mm(depth)

    assert quantised.dtype == np.uint16
    np.testing.assert_allclose(quantised / annotate.DEPTH_SCALE_MM, depth, atol=5e-4)


def test_quantise_depth_clips_rather_than_wrapping():
    """Depth beyond the uint16 range must saturate, because wrapping would invent near geometry."""
    depth = np.array([[-1.0, 1e6]], dtype=np.float32)

    quantised = annotate.quantise_depth_mm(depth)

    assert quantised.tolist() == [[0, annotate.DEPTH_UINT16_MAX]]
