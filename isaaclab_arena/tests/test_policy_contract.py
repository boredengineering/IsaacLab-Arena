# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure, SDK-free policy provenance validation."""

import pytest

from isaaclab_arena.agentic_environment_generation import policy_contract

NUMPY_MARKER = b"nd"


def contract():
    return policy_contract


def server_info():
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


def droid_modalities():
    return {
        "video": {"delta_indices": [0], "modality_keys": ["exterior_image_1_left", "wrist_image_left"]},
        "state": {"delta_indices": [0], "modality_keys": ["joint_position", "gripper_position"]},
        "action": {"delta_indices": list(range(32)), "modality_keys": ["joint_position", "gripper_position"]},
        # Isaac-GR00T n1.6-release:gr00t/configs/data/embodiment_configs.py, oxe_droid.
        "language": {"delta_indices": [0], "modality_keys": ["annotation.language.language_instruction"]},
    }


def test_server_info_is_exact_detached_and_optionally_compared():
    c = contract()
    info = server_info()
    assert c.CHECKPOINT_ID == info["checkpoint_id"]
    result = c.validate_server_info(info, checkpoint_sha256="b" * 64, config_sha256="c" * 64)
    assert result == info and result is not info
    assert c.validate_server_info(info) == info  # Structural only, not operator approval.
    with pytest.raises(ValueError):
        c.validate_server_info(info, checkpoint_sha256="f" * 64)
    with pytest.raises(ValueError):
        c.validate_server_info(info, config_sha256="F" * 64)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("instance_id", "A" * 32),
        ("checkpoint_id", "nvidia/GR00T-N1.7"),
        ("embodiment", "NEW_EMBODIMENT"),
        ("serializer_sha256", "x" * 64),
        ("extra", "secret"),
    ],
)
def test_server_info_rejects_non_contract_values(field, value):
    info = server_info()
    info[field] = value
    with pytest.raises(ValueError):
        contract().validate_server_info(info)


def test_modalities_normalize_native_and_wire_wrappers_and_digest():
    import json
    from dataclasses import make_dataclass

    c = contract()
    plain = droid_modalities()
    native_type = make_dataclass("ModalityConfig", ["delta_indices", "modality_keys", ("action_configs", object, None)])
    native = {key: native_type(**value) for key, value in plain.items()}
    wrapped = {key: {"__ModalityConfig__": True, "as_json": json.dumps(value)} for key, value in plain.items()}
    assert c.normalize_modalities(native) == plain
    assert c.validate_droid_modalities(wrapped) == plain
    assert c.canonical_metadata_digest(c.normalize_modalities(native)) == c.canonical_metadata_digest(plain)
    assert c.canonical_metadata_digest({"b": 2, "a": 1}) == c.canonical_metadata_digest({"a": 1, "b": 2})
    result = c.validate_droid_modalities(plain)
    result["video"]["delta_indices"].append(1)
    assert plain["video"]["delta_indices"] == [0]


@pytest.mark.parametrize(
    "field,value",
    [
        ("video", {"delta_indices": [-15, 0], "modality_keys": ["exterior_image_1_left", "wrist_image_left"]}),
        ("language", {"delta_indices": [0], "modality_keys": ["language_instruction"]}),
        ("state", {"delta_indices": [True], "modality_keys": ["joint_position", "gripper_position"]}),
        ("extra", {}),
    ],
)
def test_modalities_reject_mismatch(field, value):
    data = droid_modalities()
    data[field] = value
    with pytest.raises(ValueError):
        contract().validate_droid_modalities(data)


@pytest.mark.parametrize("value", [float("nan"), {"x": b"bytes"}, {1: "key"}, [0] * 10000])
def test_canonical_digest_rejects_non_bounded_json(value):
    with pytest.raises(ValueError):
        contract().canonical_metadata_digest(value)


def npy_wire_header(shape=(2**50,), descr="<f8", payload=b""):
    import struct

    header = repr({"descr": descr, "fortran_order": False, "shape": shape}).encode() + b"\n"
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header + payload


@pytest.mark.parametrize("wire", ["legacy", "current", "object", "negative", "boolshape", "truncated", "extra"])
def test_raw_array_headers_rejected_before_allocation_decoder(wire):
    import msgpack

    legacy = {"__ndarray_class__": True, "as_npy": npy_wire_header()}
    if wire == "current":
        legacy = {NUMPY_MARKER: True, b"type": "<f8", b"kind": b"", b"shape": [2**50], b"data": b""}
    elif wire == "object":
        legacy["as_npy"] = npy_wire_header((1,), "|O", b"pickle")
    elif wire == "negative":
        legacy["as_npy"] = npy_wire_header((-1,))
    elif wire == "boolshape":
        legacy["as_npy"] = npy_wire_header((True,))
    elif wire == "truncated":
        legacy["as_npy"] = npy_wire_header((2,), "<f8", b"\0")
    elif wire == "extra":
        legacy["unexpected"] = True

    def poisoned_decoder(raw):
        pytest.fail("Allocation decoder reached unvalidated raw array")

    with pytest.raises(ValueError):
        contract().safe_decode_native_message(msgpack.packb({"nested": [legacy]}), poisoned_decoder)


def test_raw_preflight_rejects_malformed_envelopes_and_aggregate_allocations():
    import msgpack

    def poison(raw):
        pytest.fail("Decoder must not see malformed or oversized raw bytes")

    array = {NUMPY_MARKER: True, b"type": "<f4", b"kind": b"", b"shape": [2], b"data": b"\0" * 8}
    invalid = [
        b"",
        b"\xc1",
        b"\x91",
        b"\x82\xa1x\x00\xa1x\x01",
        msgpack.packb(msgpack.ExtType(1, b"x")),
        msgpack.packb([array, array]),
    ]
    for raw in invalid:
        with pytest.raises(ValueError):
            contract().safe_decode_native_message(raw, poison, max_array_bytes=8)


@pytest.mark.parametrize("wire", ["legacy", "current"])
def test_raw_preflight_accepts_exact_bounded_numeric_bytes(wire):
    import struct

    import msgpack

    data = struct.pack("<ff", 1.0, 2.0)
    value = (
        {"__ndarray_class__": True, "as_npy": npy_wire_header((2,), "<f4", data)}
        if wire == "legacy"
        else {NUMPY_MARKER: True, b"type": "<f4", b"kind": b"", b"shape": [2], b"data": data}
    )
    raw = msgpack.packb(value)
    assert contract().preflight_native_message(raw) == value
    assert contract().native_array_metadata(value, max_array_bytes=8) == {
        "shape": [2],
        "dtype": "<f4",
        "bytes": 8,
    }
    assert contract().safe_decode_native_message(raw, lambda checked: checked) == raw
    with pytest.raises(ValueError):
        contract().preflight_native_message(raw, max_array_bytes=4)
    with pytest.raises(ValueError):
        contract().preflight_native_message(raw, max_bytes=4)


@pytest.mark.parametrize(
    "marker,payload",
    [(b"__ndarray_class__", b"as_npy"), (b"__ndarray_class__", "as_npy"), ("__ndarray_class__", b"as_npy")],
)
def test_native_legacy_aliases_are_refused_even_for_small_arrays(marker, payload):
    import msgpack

    value = {marker: True, payload: npy_wire_header((1,), "|u1", b"\x01")}
    with pytest.raises(ValueError):
        contract().native_array_metadata(value)
    with pytest.raises(ValueError):
        contract().safe_decode_native_message(
            msgpack.packb({"nested": [value]}),
            lambda raw: pytest.fail("Aliased native wrapper reached decoder"),
        )
