# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Synthetic N1.6 wire compatibility with preallocation refusal at the API boundary."""

import io
import numpy as np

import msgpack
import pytest

from isaaclab_arena_examples.agentic_environment_generation.web_api.policy_readiness import decode_codec_reply


def info():
    return {
        "schema_version": 1,
        "instance_id": "a" * 32,
        "checkpoint_id": "nvidia/GR00T-N1.6-DROID",
        "checkpoint_sha256": "b" * 64,
        "config_sha256": "c" * 64,
        "embodiment": "OXE_DROID",
        "serializer_sha256": "d" * 64,
        "modalities_sha256": "e" * 64,
    }


def legacy_array(value):
    """Match N1.6 ead52833's MsgSerializer.encode_custom_classes without importing its model."""
    stream = io.BytesIO()
    np.save(stream, value, allow_pickle=False)
    return {"__ndarray_class__": True, "as_npy": stream.getvalue()}


def envelope():
    return {
        "server_info": info(),
        "probe": {
            "nonce": "f" * 32,
            "numeric": legacy_array(np.array([[0, -1.5, 2.25, 17]], dtype=np.float32)),
            "image": legacy_array(np.arange(18, dtype=np.uint8).reshape(1, 2, 3, 3)),
        },
    }


def test_n16_codec_reply_reaches_native_decoder_after_preflight():
    payload = msgpack.packb(envelope())
    called = []

    def native(raw):
        called.append(raw)

        def decode(obj):
            if "__ndarray_class__" in obj:
                return np.load(io.BytesIO(obj["as_npy"]), allow_pickle=False)
            return obj

        return msgpack.unpackb(raw, object_hook=decode)

    result = decode_codec_reply(payload, native)
    assert called == [payload]
    assert result["server_info"] == info()
    assert result["probe"]["numeric"].dtype == np.float32
    assert result["probe"]["image"].shape == (1, 2, 3, 3)
    assert result["probe"]["image"].tobytes() == bytes(range(18))


@pytest.mark.parametrize("shape,descr", [((2**60,), "<f4"), ((1, 4), "|O"), ((1, 4), "<f4")])
def test_npy_header_cannot_reach_native_allocation_before_body_validation(shape, descr):
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        stream,
        {
            "descr": descr,
            "fortran_order": False,
            "shape": shape,
        },
    )
    value = envelope()
    value["probe"]["numeric"]["as_npy"] = stream.getvalue()  # No body, regardless of claimed shape.
    called = []
    with pytest.raises(ValueError):
        decode_codec_reply(msgpack.packb(value), lambda raw: called.append(raw))
    assert called == []


def test_n16_wrong_probe_shape_is_refused_before_native_decode():
    value = envelope()
    value["probe"]["image"] = legacy_array(np.zeros((18,), dtype=np.uint8))
    called = []
    with pytest.raises(ValueError):
        decode_codec_reply(msgpack.packb(value), lambda raw: called.append(raw))
    assert called == []


def test_n16_non_null_action_configuration_keeps_native_and_wire_digests_equal():
    from gr00t.data.types import ActionConfig, ActionFormat, ActionRepresentation, ActionType, ModalityConfig
    from gr00t.policy.server_client import MsgSerializer

    from isaaclab_arena.agentic_environment_generation.policy_contract import (
        canonical_metadata_digest,
        validate_droid_modalities,
    )
    from isaaclab_arena_examples.agentic_environment_generation.web_api.policy_readiness import decode_metadata

    # N1.6 release oxe_droid uses relative internal arm actions and absolute gripper actions.
    native = {
        "video": ModalityConfig([0], ["exterior_image_1_left", "wrist_image_left"]),
        "state": ModalityConfig([0], ["joint_position", "gripper_position"]),
        "action": ModalityConfig(
            list(range(32)),
            ["joint_position", "gripper_position"],
            action_configs=[
                ActionConfig(ActionRepresentation.RELATIVE, ActionType.NON_EEF, ActionFormat.DEFAULT),
                ActionConfig(ActionRepresentation.ABSOLUTE, ActionType.NON_EEF, ActionFormat.DEFAULT),
            ],
        ),
        "language": ModalityConfig([0], ["annotation.language.language_instruction"]),
    }
    decoded = decode_metadata(MsgSerializer.to_bytes(native))
    expected = validate_droid_modalities(native)
    observed = validate_droid_modalities(decoded)
    assert observed == expected
    assert observed["action"]["action_configs"][0]["rep"] == "RELATIVE"
    assert canonical_metadata_digest(observed) == canonical_metadata_digest(expected)
