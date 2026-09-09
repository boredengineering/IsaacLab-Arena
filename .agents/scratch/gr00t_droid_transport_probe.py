# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Exercise the real DROID server with explicitly synthetic transport-test inputs."""

import argparse
import json
import numpy as np
from pathlib import Path

from gr00t.policy.server_client import MsgSerializer, PolicyClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5559)
    parser.add_argument("--payload-path", type=Path)
    args = parser.parse_args()
    observation = {
        "video": {
            key: np.zeros((1, 1, 180, 320, 3), dtype=np.uint8) for key in ("exterior_image_1_left", "wrist_image_left")
        },
        "state": {
            "joint_position": np.zeros((1, 1, 7), dtype=np.float32),
            "gripper_position": np.zeros((1, 1, 1), dtype=np.float32),
        },
        "language": {"annotation.language.language_instruction": [["Pick up the apple and place it into the bowl."]]},
    }
    if args.payload_path:
        args.payload_path.write_bytes(MsgSerializer.to_bytes(observation))
    client = PolicyClient(host="127.0.0.1", port=args.port, timeout_ms=120000)
    try:
        assert client.ping(), "Server did not respond"
        modalities = client.get_modality_config()
        assert modalities["video"].modality_keys == list(observation["video"])
        assert len(modalities["action"].delta_indices) == 32
        print("DROID modalities and server ping verified", flush=True)
        action, info = client.get_action(observation)
        for key, dimension in (("joint_position", 7), ("gripper_position", 1)):
            assert isinstance(action[key], np.ndarray), (key, type(action[key]))
            assert action[key].shape == (1, 32, dimension), (key, action[key].shape)
            assert np.isfinite(action[key]).all(), key
        print(
            json.dumps({
                "synthetic_transport_probe": "PASS",
                "actions": {
                    key: {"shape": list(value.shape), "dtype": str(value.dtype)} for key, value in action.items()
                },
            }),
            flush=True,
        )
    finally:
        # Destroy every socket, including any recreated by timeout handling.
        client.context.destroy(linger=0)
        client._closed = True


if __name__ == "__main__":
    main()
