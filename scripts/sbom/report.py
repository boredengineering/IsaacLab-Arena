# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Validate paired source collections and write a bounded, reproducible coverage report."""

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

from validate import normalized_inventory, validate


def load(path):
    """Read a local JSON artifact."""
    return json.loads(path.read_text())


def digest(data):
    """Hash bytes without interpreting component identities."""
    return hashlib.sha256(data).hexdigest()


def report(snapshot, repeat, schemas):
    """Write local summary and checksums; do not change scanner outputs or source inputs."""
    checks = []
    for path in (snapshot, repeat):
        validation, coverage = validate(path, schemas)
        if not validation["ok"]:
            raise ValueError(f"collection validation failed: {path / 'validation.json'}")
        checks.append((validation, coverage))
    native = load(snapshot / "source/repository.syft.json")
    other = load(repeat / "source/repository.syft.json")
    collection = load(snapshot / "collection.json")
    repeated = load(repeat / "collection.json")
    for key in ("root_commit", "scope_sha256", "input_manifest_sha256", "scanner_sha256"):
        if collection[key] != repeated[key]:
            raise ValueError("repeat does not have the same frozen subject/inputs/tool")
    normalized = [
        json.dumps(normalized_inventory(n), sort_keys=True, separators=(",", ":")).encode() for n in (native, other)
    ]
    if normalized[0] != normalized[1]:
        raise ValueError("normalized package identities/origins/dependency edges differ")
    validation, coverage = checks[0]
    scope = load(snapshot / "scope.json")
    inventory = load(snapshot / "input-manifest.json")
    counters = Counter(e["status"] for i in coverage["inputs"] for e in i["entries"])
    proof = {
        "structural_validation": True,
        "source_coverage_complete": False,
        "repeat_snapshot": str(repeat),
        "repeat_normalized_equal": True,
        "normalized_inventory_sha256": digest(normalized[0]),
        "root_commit": collection["root_commit"],
        "source_only": True,
        "input_count": len(inventory["files"]),
        "scanner_input_count": sum(e["scan"] for e in inventory["files"]),
        "packages": len(native["artifacts"]),
        "ecosystems": dict(Counter(p["type"] for p in native["artifacts"])),
        "lock_entries": sum(counters.values()),
        "lock_entry_statuses": dict(counters),
        "declaration_gaps": coverage["declaration_gaps"],
        "not_performed": [
            "application installation/resolution",
            "image/runtime inspection",
            "simulation/inference",
            "database access",
            "vulnerability scanning",
            "publication",
        ],
        "validation_scope": (
            "Frozen scope membership, recorded source identity, hashes and repeat inventory checked locally; no"
            " complete-coverage approval or external attestation is implied."
        ),
    }
    lines = [
        "# Source-dependency SBOM coverage report",
        "",
        (
            "Status: real collection and structural validation passed; source coverage is PARTIAL, not an installed or"
            " release inventory."
        ),
        "",
        (
            f"Subject: `{collection['root_commit']}`; dirty checkout: `{collection['dirty']}`. See captured scope and"
            " per-file hashes rather than treating the commit as the entire subject."
        ),
        "",
        "## Results",
        "",
        (
            f"- {proof['packages']} scanner package records: {proof['ecosystems']}. These are records across"
            " sources/alternatives, not a count of unique installed dependencies."
        ),
        (
            f"- {proof['input_count']} captured metadata inputs; {proof['scanner_input_count']} scanned; the remainder"
            " are context-only."
        ),
        (
            f"- {proof['lock_entries']} lock entries reconciled by ecosystem/name/version/source-file location:"
            f" {dict(counters)}."
        ),
        (
            f"- {len(validation['summary']['unknown_licenses'])} emitted package records have no detected license. No"
            " license clearance is asserted."
        ),
        (
            "- Both actual offline collections have the same normalized package/origin/edge inventory:"
            f" `{proof['normalized_inventory_sha256']}`."
        ),
        (
            "- Official pinned CycloneDX 1.6 schemas, package/reference consistency, frozen scope membership, source"
            " identity and captured hashes checked."
        ),
        (
            "- `validation.ok` covers those structural checks and existing lock entries only."
            " `source_coverage_complete` is false."
        ),
        "",
        "## Manifest/lock drift requiring follow-up",
        "",
        "Declared root requirements without compatible locked or scanned candidates:",
        "",
    ]
    lines.extend(
        f"- `{r['declaration']}` ({r['group']}): locked candidates={r['lock_candidates']}; scanned"
        f" candidates={len(r['inventory_candidates'])}. No version was invented and no resolver was run."
        for r in coverage["declaration_gaps"]
    )
    lines += ["", "Root requirements not named in the locked root package's `requires-dist` metadata:", ""]
    lines.extend(f"- `{r['declaration']}` ({r['group']})." for r in coverage["root_lock_metadata_drift"])
    lines += [
        "",
        (
            "These gaps remain visible in coverage.json. The raw scanner SBOMs are unmodified and therefore do not"
            " contain the missing declarations. Root comparison retains all extras/groups and does not select a"
            " deployment, evaluate markers, resolve source mappings, or prove dependency-graph completeness."
        ),
        "",
        "## Coverage limits",
        "",
    ]
    lines.extend("- " + gap for gap in scope.get("coverage_holes", []))
    lines += [
        (
            "- Non-lock manifests and requirements are only partially reconciled; dynamic setup metadata is never"
            " executed. A populated version on each emitted record does not mean every declaration was emitted or"
            " resolved."
        ),
        (
            "- Source-origin/profile ambiguities are diagnostic, not authenticated fork provenance. License files are"
            " scoped evidence, not automatic attribution to dependencies."
        ),
        (
            "- Tool bootstrap: Syft's official checksum signature verified with Cosign; Cosign itself was acquired by"
            " official HTTPS and pinned GitHub asset hash, not independently signature-verified. See"
            " tool-provenance.json."
        ),
        (
            "- Local checksums detect changes against retained records; they are not externally signed attestations and"
            " cannot prevent an actor rewriting the entire evidence set."
        ),
        "- No vulnerability or exploitability verdict; no published artifacts; all files remain local and Git-ignored.",
        "",
        "## Files",
        "",
        "- source/repository.cdx.json — primary CycloneDX 1.6 source scan.",
        "- source/repository.syft.json — same scan's native evidence.",
        "- coverage.json — per-input, lock-entry and root-declaration diagnostics.",
        "- validation.json / verification.json — structural validation and actual repeat proof.",
        "- collection.json / scope.json / input-manifest.json — frozen subject, selection and hashes.",
        "- inputs/ and context/ — captured allowlist, never the whole workspace.",
        "- tool-provenance.json / logs/ / checksums.sha256 — tool verification, commands and integrity manifest.",
    ]
    (snapshot / "coverage.md").write_text("\n".join(lines) + "\n")
    (snapshot / "verification.json").write_text(json.dumps(proof, indent=2) + "\n")
    for name in ("validate.py", "report.py"):
        shutil.copyfile(Path(__file__).with_name(name), snapshot / name)
    paths = sorted(p for p in snapshot.rglob("*") if p.is_file() and p.name != "checksums.sha256")
    (snapshot / "checksums.sha256").write_text(
        "".join(f"{digest(p.read_bytes())}  {p.relative_to(snapshot)}\n" for p in paths)
    )
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--repeat", required=True, type=Path)
    parser.add_argument("--schemas", required=True, type=Path)
    args = parser.parse_args()
    result = report(args.snapshot.resolve(), args.repeat.resolve(), args.schemas.resolve())
    print(
        json.dumps({
            "report": str(args.snapshot / "coverage.md"),
            "packages": result["packages"],
            "source_coverage_complete": False,
        })
    )
