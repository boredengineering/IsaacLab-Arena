# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Generate explicitly synthetic test inputs and REAL offline Syft fixture outputs."""

import json
import os
import subprocess
from pathlib import Path

from collect import SYFT_SHA256, sha256


def main():
    """Use previously admitted tools; never download or resolve application dependencies."""
    root = Path(__file__).resolve().parents[2]
    tooling = root / "outputs/sbom/tooling"
    syft = tooling / "syft-1.46.0/syft"
    if sha256(syft.read_bytes()) != SYFT_SHA256:
        raise ValueError("fixture scanner hash mismatch")
    fixture = tooling / "fixture"
    fixture.mkdir(exist_ok=True)
    if fixture.is_symlink() or fixture.resolve() != fixture:
        raise ValueError("fixture must be a regular local tooling directory")
    for name in ("uv.lock", "package-lock.json"):
        if (fixture / name).is_symlink():
            raise ValueError("fixture input symlink")
    (fixture / "uv.lock").write_text(
        'version = 1\nrevision = 3\nrequires-python = ">=3.12"\n'
        '[[package]]\nname = "fixture-root"\nversion = "0.0.0"\nsource = { virtual = "." }\n'
        'dependencies = [{ name = "fixture-leaf" }]\n'
        '[[package]]\nname = "fixture-leaf"\nversion = "1.2.3"\n'
        'source = { registry = "https://pypi.org/simple" }\n'
    )
    (fixture / "package-lock.json").write_text(
        json.dumps({
            "name": "fixture-web",
            "version": "0.0.0",
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "fixture-web", "version": "0.0.0", "dependencies": {"fixture-npm": "1.2.3"}},
                "node_modules/fixture-npm": {
                    "version": "1.2.3",
                    "resolved": "https://registry.npmjs.org/fixture-npm/-/fixture-npm-1.2.3.tgz",
                    "license": "MIT",
                },
            },
        })
    )
    (tooling / "home").mkdir(exist_ok=True)
    command = [
        "unshare",
        "-n",
        "--",
        str(syft),
        "scan",
        f"dir:{fixture}",
        "--config",
        str(Path(__file__).with_name("syft.yaml")),
        "--source-name",
        "synthetic-sbom-test-fixture",
        "--source-version",
        "0.0.0",
        "-o",
        f"syft-json={tooling / 'fixture.syft.json'}",
        "-o",
        f"cyclonedx-json@1.6={tooling / 'fixture.cdx.json'}",
    ]
    subprocess.run(command, env={"HOME": str(tooling / "home"), "PATH": "/usr/bin:/bin"}, check=True, timeout=120)
    native = json.loads((tooling / "fixture.syft.json").read_text())
    expected = {("fixture-leaf", "1.2.3"), ("fixture-npm", "1.2.3")}
    if not expected <= {(p["name"], p["version"]) for p in native["artifacts"]}:
        raise ValueError("actual scanner did not recognize both lockfile ecosystems")
    print(json.dumps({"fixture_scan": "verified", "network_isolated": True, "uid": os.getuid()}))


if __name__ == "__main__":
    main()
