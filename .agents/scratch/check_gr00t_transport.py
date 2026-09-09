# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Compare the image's N1.6 transport with Arena's transport using a captured test payload."""

import importlib.util
import numpy as np
import sys
from pathlib import Path

import msgpack
from gr00t.policy.server_client import MsgSerializer as ImageSerializer

spec = importlib.util.spec_from_file_location("gr00t.policy.arena_transport", "/tmp/arena_server_client.py")
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
serializer = module.MsgSerializer
payload = Path("/tmp/droid_transport.msgpack").read_bytes()
old = ImageSerializer.from_bytes(payload)
print("Image decoder video type:", type(old["video"]["exterior_image_1_left"]).__name__)
assert isinstance(old["video"]["exterior_image_1_left"], dict)
new = serializer.from_bytes(payload)
for group in ("video", "state"):
    for key, value in new[group].items():
        assert isinstance(value, np.ndarray), (group, key, type(value))
        roundtrip = serializer.from_bytes(serializer.to_bytes(value))
        np.testing.assert_array_equal(value, roundtrip)
        assert value.dtype == roundtrip.dtype
        legacy = ImageSerializer.to_bytes(value)
        np.testing.assert_array_equal(value, serializer.from_bytes(legacy))
for encode in (ImageSerializer.to_bytes, serializer.to_bytes):
    try:
        encode(np.array([object()], dtype=object))
    except (TypeError, ValueError):
        pass
    else:
        raise AssertionError("Object arrays must not be serialized")
for forged in ({b"nd": True, b"kind": b"O", b"data": b"not-a-pickle"}, {"nd": 1, "kind": "O"}):
    try:
        serializer.from_bytes(msgpack.packb(forged))
    except ValueError:
        pass
    else:
        raise AssertionError("Pickle-bearing envelopes must be rejected")
print("PASS: new wire roundtrip, legacy decode, and object/pickle rejection")
