#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Build and browser-check the offline UI preview using installed isolated images."""
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path

FRONT = Path(__file__).resolve().parents[1]
OUT = None
RUN = None
OWNED = []
PROOF = {}


def command(args, timeout=180):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Command failed: {result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def docker(*args, timeout=180):
    return command(["docker", *args], timeout)


def inspect(identity):
    return json.loads(docker("inspect", identity, timeout=30))[0]


def export_directory(cid, remote, destination):
    result = subprocess.run(
        ["docker", "exec", "--user", "1000:1234", cid, "tar", "-C", remote, "-cf", "-", "."],
        capture_output=True,
        timeout=30,
    )
    if result.returncode:
        return False
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        archive.extractall(destination, filter="data")
    return True


def import_artifact(cid, directory):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as archive:
        archive.add(directory, arcname="arena-ui-preview-dist")
    result = subprocess.run(
        ["docker", "exec", "-i", "--user", "1000:1234", cid, "tar", "-C", "/tmp", "--no-same-owner", "-xf", "-"],
        input=payload.getvalue(),
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, "Could not transfer compiled preview into browser sandbox"


def snapshot():
    files = [
        *FRONT.joinpath("src/preview").rglob("*"),
        *FRONT.glob("preview.*"),
        FRONT / "scripts/package-preview.mjs",
        FRONT / "scripts/run-preview.py",
        FRONT / "tests/preview-package.test.mjs",
        FRONT / "tests/preview_launcher_test.py",
        FRONT / "tests/e2e/preview-browser.mjs",
    ]
    return {str(p.relative_to(FRONT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files) if p.is_file()}


def start(label, image, host_source, deps):
    resource = {"name": f"{RUN}-{label}", "label": RUN, "id": None}
    assert not any(r["name"] == resource["name"] for r in OWNED), "Duplicate intended name"
    OWNED.append(resource)
    cid = docker(
        "run",
        "-d",
        "--pull=never",
        "--name",
        f"{RUN}-{label}",
        "--label",
        f"arena.ui-preview={RUN}",
        "--network",
        "none",
        "--read-only",
        "--init",
        "--user",
        "1000:1234",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/tmp:rw,mode=1777",
        "--env",
        "HOME=/tmp",
        "--mount",
        f"type=bind,src={host_source},dst=/app,readonly",
        "--mount",
        f"type=volume,src={deps},dst=/app/node_modules,readonly",
        "--workdir",
        "/app",
        "--entrypoint",
        "sh",
        image,
        "-c",
        "sleep infinity",
    )
    resource["id"] = cid
    info = inspect(cid)
    assert info["HostConfig"]["NetworkMode"] == "none"
    assert {m["Destination"] for m in info["Mounts"]} == {"/app", "/app/node_modules"}
    assert all(not m["RW"] for m in info["Mounts"])
    PROOF["containers"].append(
        {"id": cid, "role": label, "image": info["Image"], "network": "none", "user": "1000:1234"}
    )
    probe = """const net=require('node:net'),os=require('node:os');
if(Object.keys(os.networkInterfaces()).some(n=>n!=='lo'))throw Error('Network interface present');
const s=net.connect({host:'198.18.0.1',port:9});s.setTimeout(1000,()=>{s.destroy();process.exit(2)});
s.on('connect',()=>{s.destroy();process.exit(3)});s.on('error',e=>{
if(!['ENETUNREACH','EHOSTUNREACH'].includes(e.code))process.exit(4);console.log('egress denied before imports')});"""
    docker("exec", "--user", "1000:1234", cid, "node", "-e", probe, timeout=10)
    return cid


def container_names():
    """Return an authoritative name/identity listing, or raise on daemon failure."""
    output = docker("ps", "-a", "--no-trunc", "--format", "{{.ID}} {{.Names}}", timeout=30)
    return {name: cid for cid, name in (line.split() for line in output.splitlines())}


def cleanup():
    """Remove only checked run-owned identities and independently verify absence."""
    refused = False
    for resource in reversed(OWNED):
        record = {**resource, "removed": False}
        PROOF["cleanup"].append(record)
        try:
            cid = container_names().get(resource["name"])
            if cid is None:
                record["absent_before"] = True
                continue
            info = inspect(cid)
            if (
                info["Id"] != cid
                or info["Name"] != "/" + resource["name"]
                or info["Config"].get("Labels", {}).get("arena.ui-preview") != resource["label"]
                or (resource["id"] is not None and resource["id"] != cid)
            ):
                record["refused"] = "Container ownership/identity mismatch"
                refused = True
                continue
            record["id"] = cid
            docker("rm", "-f", cid, timeout=30)
            record["removed"] = True
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {error}"
    try:
        names = container_names()
        remaining = docker(
            "ps", "-a", "-q", "--no-trunc", "--filter", f"label=arena.ui-preview={RUN}", timeout=30
        ).splitlines()
        PROOF["owned_remaining"] = remaining
        for record in PROOF["cleanup"]:
            record["absent"] = record["name"] not in names and record["id"] not in names.values()
        verified = not refused and not remaining and all(r["absent"] for r in PROOF["cleanup"])
    except Exception as error:
        PROOF["owned_remaining"] = None
        PROOF["cleanup_error"] = f"{type(error).__name__}: {error}"
        verified = False
    PROOF["cleanup_verified"] = verified
    return verified


def run_acceptance():
    assert OUT is not None, "Acceptance requires an initialized output directory"
    containers = [inspect(cid) for cid in docker("ps", "-q").splitlines()]
    editor = next(c for c in containers if any(m["Destination"] == str(FRONT.parents[1]) for m in c["Mounts"]))
    host_root = next(m["Source"] for m in editor["Mounts"] if m["Destination"] == str(FRONT.parents[1]))
    host_source = host_root + "/web/arena-workbench"
    frontend = next(
        c for c in containers if any(m["Source"] == host_source and m["Destination"] == "/app" for m in c["Mounts"])
    )
    deps = next(m["Name"] for m in frontend["Mounts"] if m["Destination"] == "/app/node_modules")
    PROOF["source_before"] = snapshot()
    node = start("build", "node:22.22.0-bookworm-slim", host_source, deps)
    for label, args in [
        (
            "unit",
            [
                "node",
                "node_modules/vitest/vitest.mjs",
                "run",
                "--config",
                "preview.test.config.ts",
                "--configLoader",
                "runner",
            ],
        ),
        ("package-unit", ["node", "--test", "tests/preview-package.test.mjs"]),
        ("typecheck", ["node", "node_modules/typescript/bin/tsc", "--noEmit"]),
        (
            "build",
            [
                "node",
                "node_modules/vite/bin/vite.js",
                "build",
                "--config",
                "preview.vite.config.ts",
                "--configLoader",
                "runner",
            ],
        ),
        ("package", ["node", "scripts/package-preview.mjs"]),
    ]:
        output = docker("exec", "--user", "1000:1234", "-w", "/app", node, *args)
        (OUT / f"{label}.log").write_text(output)
        print(f"{label}: passed", flush=True)
    assert export_directory(node, "/tmp/arena-ui-preview-dist", OUT / "artifact"), "Could not export preview artifact"
    browser = start("browser", "mcr.microsoft.com/playwright:v1.58.2-noble", host_source, deps)
    import_artifact(browser, OUT / "artifact")
    try:
        output = docker(
            "exec", "--user", "1000:1234", "-w", "/app", browser, "node", "tests/e2e/preview-browser.mjs", timeout=180
        )
        (OUT / "browser.log").write_text(output)
    finally:
        PROOF["browser_evidence_copied"] = export_directory(browser, "/tmp/preview-browser-evidence", OUT / "browser")
    browser_proof = json.loads((OUT / "browser/browser-proof.json").read_text())
    assert browser_proof["passed"] and not browser_proof["denied"] and not browser_proof["errors"]
    PROOF["source_after"] = snapshot()
    assert PROOF["source_before"] == PROOF["source_after"], "Source changed during acceptance; rerun after edits settle"
    package = json.loads((OUT / "artifact/package-proof.json").read_text())
    artifact = OUT / "artifact/arena-workflow-preview.html"
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == package["sha256"]
    PROOF["artifact"] = str(artifact)
    PROOF["artifact_sha256"] = package["sha256"]


def main():
    global OUT, RUN, OWNED, PROOF
    OUT = Path(tempfile.mkdtemp(prefix="arena-ui-preview-"))
    RUN = "arena-ui-preview-" + uuid.uuid4().hex
    OWNED = []
    PROOF = {"run": RUN, "output": str(OUT), "status": "starting", "containers": [], "cleanup": []}
    try:
        run_acceptance()
        PROOF["status"] = "cleanup_pending"
    except Exception as error:
        PROOF["status"] = "failed"
        PROOF["failure"] = f"{type(error).__name__}: {error}"
        print(str(error), flush=True)
    finally:
        try:
            verified = cleanup()
        except Exception as error:
            verified = False
            PROOF["cleanup_verified"] = False
            PROOF["owned_remaining"] = None
            PROOF["cleanup_error"] = f"{type(error).__name__}: {error}"
        if not verified:
            PROOF["status"] = "failed"
            PROOF.setdefault("failure", "Cleanup unverified or resources remain")
        elif PROOF["status"] == "cleanup_pending":
            PROOF["status"] = "passed"
        (OUT / "run-proof.json").write_text(json.dumps(PROOF, indent=2) + "\n")
        print(OUT, flush=True)
    return 0 if PROOF["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
