# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Check host-network editor forwarding policy without Docker or Arena imports."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class HostNetworkPortsTest(unittest.TestCase):
    def test_host_network_does_not_create_or_restore_application_tunnels(self):
        """Host-network listeners must be reached directly, not through themselves."""
        config = json.loads((ROOT / ".devcontainer/devcontainer.json").read_text())
        self.assertIn("--network=host", config["runArgs"])
        self.assertEqual(config.get("forwardPorts"), [])
        self.assertEqual(config.get("otherPortsAttributes"), {"onAutoForward": "ignore"})
        settings = config["customizations"]["vscode"]["settings"]
        workspace = json.loads((ROOT / ".vscode/settings.json").read_text())
        for key in ("remote.autoForwardPorts", "remote.restoreForwardedPorts"):
            with self.subTest(setting=key):
                self.assertIs(settings.get(key), False)
                self.assertIs(workspace.get(key), False)


if __name__ == "__main__":
    unittest.main()
