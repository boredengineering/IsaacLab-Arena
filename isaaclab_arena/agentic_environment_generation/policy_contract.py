# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""SDK-free, strict public metadata contract; structural validity is not approval."""

import hashlib
import json
import math
import re
from dataclasses import fields, is_dataclass
from enum import Enum


def _plain(value, depth=0):
    if depth > 16:
        raise ValueError("Metadata nesting limit")
    if value is None or type(value) in (bool, int, str):
        if type(value) is str and len(value) > 16384:
            raise ValueError("Metadata string limit")
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is list and len(value) <= 4096:
        return [_plain(item, depth + 1) for item in value]
    if type(value) is dict and len(value) <= 4096 and all(type(key) is str for key in value):
        return {key: _plain(item, depth + 1) for key, item in value.items()}
    raise ValueError("Invalid plain metadata")


def canonical_metadata_digest(value):
    """Hash bounded JSON using sorted keys, compact separators and UTF-8."""
    encoded = json.dumps(
        _plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    if len(encoded) > 65536:
        raise ValueError("Metadata byte limit")
    return hashlib.sha256(encoded).hexdigest()


def _native_plain(value, depth=0):
    if depth > 16:
        raise ValueError("Metadata nesting limit")
    if isinstance(value, Enum):
        return value.name
    if is_dataclass(value) and not isinstance(value, type):
        value = {field.name: getattr(value, field.name) for field in fields(value)}
    if type(value) is dict:
        if len(value) > 64:
            raise ValueError("Metadata field limit")
        return {key: _native_plain(item, depth + 1) for key, item in value.items()}
    if type(value) is list:
        if len(value) > 4096:
            raise ValueError("Metadata list limit")
        return [_native_plain(item, depth + 1) for item in value]
    return _plain(value, depth)


def normalize_modalities(value):
    """Normalize native dataclasses or bounded native wire wrappers without the SDK."""
    if type(value) is not dict or set(value) != {"video", "state", "action", "language"}:
        raise ValueError("Invalid modality groups")
    result = {}
    required = {"delta_indices", "modality_keys"}
    optional = {"sin_cos_embedding_keys", "mean_std_embedding_keys", "action_configs"}
    for key, item in value.items():
        if type(item) is dict and ("__ModalityConfig__" in item or "__ModalityConfig_class__" in item):
            marker = "__ModalityConfig__" if "__ModalityConfig__" in item else "__ModalityConfig_class__"
            if set(item) != {marker, "as_json"} or item[marker] is not True:
                raise ValueError("Invalid modality wrapper")
            item = item["as_json"]
            if type(item) in (bytes, str):
                if len(item) > 16384:
                    raise ValueError("Modality wrapper limit")
                try:
                    item = json.loads(item)
                except (ValueError, UnicodeError, RecursionError) as exc:
                    raise ValueError("Invalid modality JSON") from exc
        item = _native_plain(item)
        if type(item) is not dict or not required <= set(item) or set(item) - required - optional:
            raise ValueError("Invalid modality fields")
        delta, keys = item["delta_indices"], item["modality_keys"]
        if (
            type(delta) is not list
            or not 1 <= len(delta) <= 256
            or any(type(v) is not int or abs(v) > 256 for v in delta)
        ):
            raise ValueError("Invalid modality indices")
        if (
            type(keys) is not list
            or not 1 <= len(keys) <= 64
            or any(type(v) is not str or not v or len(v) > 256 for v in keys)
        ):
            raise ValueError("Invalid modality keys")
        if len(set(keys)) != len(keys) or len(set(delta)) != len(delta):
            raise ValueError("Duplicate modality values")
        result[key] = {name: val for name, val in item.items() if name in required or val is not None}
    canonical_metadata_digest(result)
    return result


def validate_droid_modalities(value):
    """Validate N1.6 DROID keys/horizons, retaining normalization/action metadata."""
    result = normalize_modalities(value)
    keys = {
        "video": ["exterior_image_1_left", "wrist_image_left"],
        "state": ["joint_position", "gripper_position"],
        "action": ["joint_position", "gripper_position"],
        "language": ["annotation.language.language_instruction"],
    }
    for key, names in keys.items():
        if result[key]["modality_keys"] != names or result[key]["delta_indices"] != (
            list(range(32)) if key == "action" else [0]
        ):
            raise ValueError("DROID modality mismatch")
    return result


CHECKPOINT_ID = "nvidia/GR00T-N1.6-DROID"
_HASH_FIELDS = ("checkpoint_sha256", "config_sha256", "serializer_sha256", "modalities_sha256")


def validate_server_info(value, *, checkpoint_sha256=None, config_sha256=None):
    """Return detached exact metadata, optionally comparing operator-pinned hashes."""
    fields = {"schema_version", "instance_id", "checkpoint_id", "embodiment", *_HASH_FIELDS}
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Invalid policy metadata fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Invalid policy metadata version")
    if value["checkpoint_id"] != CHECKPOINT_ID or value["embodiment"] != "OXE_DROID":
        raise ValueError("Policy profile mismatch")
    for field in ("instance_id", *_HASH_FIELDS):
        length = 32 if field == "instance_id" else 64
        if type(value[field]) is not str or re.fullmatch(r"[0-9a-f]{%d}" % length, value[field]) is None:
            raise ValueError("Invalid policy metadata digest")
    for field, expected in (("checkpoint_sha256", checkpoint_sha256), ("config_sha256", config_sha256)):
        if expected is not None and (type(expected) is not str or value[field] != expected):
            raise ValueError("Policy artifact mismatch")
    return dict(value)


NATIVE_MAX_MESSAGE_BYTES = 64 * 1024 * 1024
NUMPY_MARKERS = (b"nd", "nd")
NPY_MARKERS = ("__ndarray_class__", "as_npy", b"__ndarray_class__", b"as_npy")


def _array_byte_count(descr, shape, limit):
    # Numeric-only grammar: never hand attacker-controlled descriptors to NumPy.
    if type(descr) is bytes:
        descr = descr.decode("ascii")
    match = re.fullmatch(r"[<>=|]?([biufc])(1|2|4|8|16)", descr) if type(descr) is str else None
    if match is None:
        raise ValueError("Forbidden array dtype")
    kind, size = match[1], int(match[2])
    if size not in {"b": {1}, "i": {1, 2, 4, 8}, "u": {1, 2, 4, 8}, "f": {2, 4, 8, 16}, "c": {8, 16}}[kind]:
        raise ValueError("Forbidden array dtype")
    if type(shape) not in (list, tuple) or len(shape) > 8:
        raise ValueError("Invalid array shape")
    count = 1
    for dim in shape:
        if type(dim) is not int or not 0 <= dim <= limit:
            raise ValueError("Invalid array dimension")
        # Bound even zero-sized arrays with enormous other dimensions/strides.
        count *= max(1, dim)
        if count > limit // size:
            raise ValueError("Array allocation limit")
    return 0 if 0 in shape else count * size


def _preflight_npy(data, limit):
    import ast
    import struct

    if type(data) is not bytes or len(data) < 10 or data[:6] != b"\x93NUMPY":
        raise ValueError("Invalid NPY header")
    version = data[6:8]
    if version == b"\x01\x00":
        start, length = 10, struct.unpack("<H", data[8:10])[0]
    elif version in (b"\x02\x00", b"\x03\x00") and len(data) >= 12:
        start, length = 12, struct.unpack("<I", data[8:12])[0]
    else:
        raise ValueError("Unsupported NPY version")
    if not 1 <= length <= 4096 or start + length > len(data):
        raise ValueError("NPY header limit")
    header = ast.literal_eval(data[start : start + length].decode("utf-8" if version[0] == 3 else "latin1"))
    if (
        type(header) is not dict
        or set(header) != {"descr", "fortran_order", "shape"}
        or type(header["fortran_order"]) is not bool
        or type(header["shape"]) is not tuple
    ):
        raise ValueError("Invalid NPY fields")
    size = _array_byte_count(header["descr"], header["shape"], limit)
    if len(data) - start - length != size:
        raise ValueError("NPY payload length mismatch")
    return {"shape": list(header["shape"]), "dtype": header["descr"], "bytes": size}


def native_array_metadata(value, *, max_array_bytes=NATIVE_MAX_MESSAGE_BYTES):
    """Describe a validated native array envelope without allocating or decoding it."""
    if type(value) is not dict:
        raise ValueError("Invalid native array")
    if any(key in value for key in NPY_MARKERS):
        # Native decoders also recognize byte aliases. Refuse aliases rather
        # than let their precedence differ from this canonical N1.6 wrapper.
        if set(value) != {"__ndarray_class__", "as_npy"} or value["__ndarray_class__"] is not True:
            raise ValueError("Invalid NPY wrapper")
        return _preflight_npy(value["as_npy"], max_array_bytes)
    obj = {(key.decode("ascii") if type(key) is bytes else key): val for key, val in value.items()}
    marker = NUMPY_MARKERS[1]
    if len(obj) != len(value) or type(obj.get(marker)) is not bool:
        raise ValueError("Invalid numpy wrapper")
    expected = {marker, "type", "kind", "shape", "data"} if obj[marker] else {marker, "type", "data"}
    if set(obj) != expected or obj.get("kind", b"") not in (b"", ""):
        raise ValueError("Invalid numpy fields")
    shape = obj.get("shape", ())
    size = _array_byte_count(obj["type"], shape, max_array_bytes)
    if type(obj["data"]) is not bytes or len(obj["data"]) != size:
        raise ValueError("Array payload length mismatch")
    dtype = obj["type"].decode("ascii") if type(obj["type"]) is bytes else obj["type"]
    return {"shape": list(shape), "dtype": dtype, "bytes": size}


def preflight_native_message(payload, *, max_bytes=NATIVE_MAX_MESSAGE_BYTES, max_array_bytes=NATIVE_MAX_MESSAGE_BYTES):
    """Return bounded raw MessagePack after validating arrays, without allocating them.

    Supports N1.6 __ndarray_class__/as_npy and msgpack-numpy numeric arrays/scalars.
    Call BEFORE any native object hook, from_bytes, np.load or NumPy allocation.
    Pickles, object/structured dtypes, extensions, duplicate keys and malformed
    shapes are forbidden. Budgets apply to the whole message, not just each array.
    """
    import msgpack

    if type(payload) is not bytes or not payload or len(payload) > max_bytes:
        raise ValueError("Native message byte limit")

    def pairs(items):
        result = {}
        for key, value in items:
            if type(key) not in (str, bytes) or key in result:
                raise ValueError("Invalid or duplicate wire key")
            result[key] = value
        return result

    def no_ext(*args):
        raise ValueError("Forbidden MessagePack extension")

    try:
        raw = msgpack.unpackb(
            payload,
            raw=False,
            strict_map_key=True,
            object_pairs_hook=pairs,
            ext_hook=no_ext,
            max_str_len=max_bytes,
            max_bin_len=max_bytes,
            max_array_len=65536,
            max_map_len=1024,
            max_ext_len=0,
        )
        nodes, allocated = 0, 0

        def visit(value, depth=0):
            nonlocal nodes, allocated
            nodes += 1
            if depth > 24 or nodes > 65536:
                raise ValueError("Native message structure limit")
            if type(value) is dict:
                if any(key in value for key in (*NPY_MARKERS, *NUMPY_MARKERS)):
                    allocated += native_array_metadata(value, max_array_bytes=max_array_bytes)["bytes"]
                for item in value.values():
                    visit(item, depth + 1)
            elif type(value) is list:
                for item in value:
                    visit(item, depth + 1)
            elif value is not None and type(value) not in (str, bytes, bool, int, float):
                raise ValueError("Invalid native wire value")
            if allocated > max_array_bytes:
                raise ValueError("Aggregate array allocation limit")

        visit(raw)
        return raw
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError, SyntaxError) as exc:
        raise ValueError("Invalid bounded native message") from exc


def safe_decode_native_message(payload, decoder, **limits):
    """Preflight raw bytes before invoking the supplied native allocation decoder."""
    preflight_native_message(payload, **limits)
    return decoder(payload)
