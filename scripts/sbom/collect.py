# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Capture approved source metadata and run pinned Syft without network access."""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

SYFT_SHA256 = "574df1a0862ff88ad933be214e81069e35b17618a13e019f8f1c84fe063222a2"
PRIVATE = {".git", ".env", ".npmrc", ".pypirc", ".netrc", ".ssh", "credentials", "secrets", "outputs"}
SENSITIVE = re.compile(
    rb"https?://[^/\s\"<>]+@|-----BEGIN [^-]*PRIVATE"
    rb" KEY-----|[?&](?:token|access_token|api_key|password|signature|X-Amz-Signature)=",
    re.I,
)


def sha256(data):
    """Return the SHA-256 digest of captured bytes."""
    return hashlib.sha256(data).hexdigest()


def dump(path, value):
    """Write a local JSON evidence artifact."""
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_input(root, relative, max_bytes=16 * 1024 * 1024):
    """Read bounded regular metadata without following path symlinks."""
    parts = PurePosixPath(relative).parts
    if not parts or relative != str(PurePosixPath(relative)) or PurePosixPath(relative).is_absolute():
        raise ValueError("non-relative input")
    if any(p in PRIVATE or p in {"..", "."} or p.startswith(".env.") for p in parts):
        raise ValueError("private or escaping input")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(file_fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > max_bytes:
                raise ValueError("input is not bounded single-link regular metadata")
            data = stream.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError("input exceeds byte bound")
    finally:
        os.close(fd)
    data.decode("utf-8")
    if SENSITIVE.search(data):
        raise ValueError("sensitive metadata detected; review without printing content")
    return data


def capture(root, entries, output):
    """Create a fresh allowlisted snapshot, with context outside the scan root."""
    paths = [e["path"] for e in entries]
    if len(paths) != len(set(paths)) or len(paths) > 2000:
        raise ValueError("duplicate or excessive scope")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    (output / "inputs").mkdir()
    (output / "context").mkdir()
    result = {"files": []}
    total = 0
    for entry in entries:
        if type(entry["scan"]) is not bool:
            raise ValueError("scan selection must be explicit boolean")
        data = read_input(root, entry["path"])
        if entry.get("sha256") and sha256(data) != entry["sha256"]:
            raise ValueError("input changed since scope discovery")
        total += len(data)
        if total > 128 * 1024 * 1024:
            raise ValueError("snapshot exceeds total byte bound")
        target = output / ("inputs" if entry["scan"] else "context") / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o444)
        result["files"].append({**entry, "sha256": sha256(data), "bytes": len(data)})
    dump(output / "input-manifest.json", result)
    return result


def git(root, *args):
    """Read local Git metadata without modifying persistent Git configuration."""
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={root}", "-c", "core.fsmonitor=false", "-C", str(root), *args],
        text=True,
        timeout=30,
    ).strip()


def scan(root, scope, output, syft, config, provenance):
    """Collect one development source snapshot; do not resolve or install dependencies."""
    if sha256(syft.read_bytes()) != SYFT_SHA256:
        raise ValueError("scanner does not match the admitted Syft 1.46.0 linux-amd64 binary")
    if shutil.which("unshare") is None:
        raise ValueError("network namespace isolation unavailable; no online fallback")
    definition = json.loads(scope.read_text())
    entries = definition["files"]
    tracked = set(git(root, "ls-files").splitlines())
    subjects = []
    for item in definition.get("submodules", []):
        path = item["path"]
        repo = root / path
        commit = git(repo, "rev-parse", "HEAD")
        if commit != item["commit"]:
            raise ValueError("submodule revision changed; review scope before collecting")
        tracked.update(f"{path}/{name}" for name in git(repo, "ls-files").splitlines())
        subjects.append({**item, "dirty": bool(git(repo, "status", "--porcelain"))})
    if any(e["path"] not in tracked for e in entries):
        raise ValueError("scope contains untracked input; explicit scope revision required")
    metadata = {
        "view": "source-dependencies-all-locked-alternatives-NOT-installed",
        "snapshot_id": output.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "root_commit": git(root, "rev-parse", "HEAD"),
        "source_name": "IsaacLab-Arena-source-dependencies",
        "branch": git(root, "branch", "--show-current"),
        "dirty": bool(git(root, "status", "--porcelain")),
        "submodules": subjects,
        "scope_sha256": sha256(scope.read_bytes()),
        "scanner_sha256": SYFT_SHA256,
        "platform": "linux-amd64 tooling; source locks include other target platforms",
        "network": "new empty Linux network namespace; clean explicit environment",
        "installed_environment_attested": False,
        "scan_completed": False,
    }
    manifest = capture(root, entries, output)
    shutil.copyfile(scope, output / "scope.json")
    shutil.copyfile(provenance, output / "tool-provenance.json")
    shutil.copyfile(config, output / "syft.yaml")
    shutil.copyfile(Path(__file__), output / "collector.py")
    (output / "source").mkdir()
    (output / "logs").mkdir()
    (output / "home").mkdir(mode=0o700)
    environment = {"HOME": str(output / "home"), "PATH": "/usr/bin:/bin", "GOMEMLIMIT": "512MiB"}
    prefix = ["unshare", "-n", "--", str(syft)]
    commands = [
        ("version", [*prefix, "version", "-o", "json"]),
        ("effective-config", [*prefix, "config", "--config", str(output / "syft.yaml")]),
        (
            "scan",
            [
                *prefix,
                "scan",
                f"dir:{output / 'inputs'}",
                "--config",
                str(output / "syft.yaml"),
                "--source-name",
                metadata["source_name"],
                "--source-version",
                metadata["root_commit"],
                "-o",
                f"syft-json={output / 'source/repository.syft.json'}",
                "-o",
                f"cyclonedx-json@1.6={output / 'source/repository.cdx.json'}",
            ],
        ),
    ]
    metadata["commands"] = []
    dump(output / "collection.json", metadata)
    for name, command in commands:
        result = subprocess.run(command, cwd=output, env=environment, capture_output=True, timeout=300)
        (output / "logs" / f"{name}.stdout").write_bytes(result.stdout)
        (output / "logs" / f"{name}.stderr").write_bytes(result.stderr)
        metadata["commands"].append({"name": name, "argv": command, "exit": result.returncode})
        dump(output / "collection.json", metadata)
        if result.returncode:
            raise RuntimeError(f"{name} failed; see bounded snapshot logs; no fallback")
    for entry in manifest["files"]:
        if sha256(read_input(root, entry["path"])) != entry["sha256"]:
            raise ValueError("original input changed during collection")
    metadata["input_manifest_sha256"] = sha256((output / "input-manifest.json").read_bytes())
    metadata["original_inputs_unchanged"] = True
    metadata["output_sha256"] = {
        f"source/repository.{suffix}.json": sha256((output / f"source/repository.{suffix}.json").read_bytes())
        for suffix in ("syft", "cdx")
    }
    metadata["scan_completed"] = True
    dump(output / "collection.json", metadata)
    return metadata


def main():
    """Collect using explicitly admitted local tools, configuration and source scope."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--scope", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--syft", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("syft.yaml"))
    parser.add_argument("--provenance", required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.absolute()
    if output.exists() or output.is_symlink() or output.resolve() != output:
        raise ValueError("output must be a new non-symlink path")
    if not output.is_relative_to(root / "outputs/sbom") or output == root / "outputs/sbom":
        raise ValueError("output must be a new snapshot beneath ignored outputs/sbom")
    subprocess.run(["git", "check-ignore", "-q", str(output / "source/repository.cdx.json")], cwd=root, check=True)
    result = scan(
        root, args.scope.resolve(), output, args.syft.resolve(), args.config.resolve(), args.provenance.resolve()
    )
    print(json.dumps({"snapshot": str(output), "scan_completed": result["scan_completed"]}))


if __name__ == "__main__":
    main()
