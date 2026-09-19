# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Offline source-union SBOM checks; never resolve or install dependencies."""

import argparse
import hashlib
import json
import re
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import jsonschema
import tomli
from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version
from referencing import Registry, Resource

SCHEMAS = {
    "bom-1.6.schema.json": "3e92dddbc30cf7f6a02b80f0942b1a4cfd4fb1c26f1dfc4310afa9d613cafb93",
    "spdx.schema.json": "baa9d3bd1ed57b6751b0887edead6b5063ff53ff7429cf85d476c6c94af0166e",
    "jsf-0.82.schema.json": "8bae002c25e723db7ee1f26afde680ae1a2b1a8f6b4b4b0fd65dc3becb090aae",
}


def check_bom(native, cdx, schemas, failures):
    """Validate local official schema and references without network retrieval."""
    try:
        resources = []
        for name, expected in SCHEMAS.items():
            raw = (Path(schemas) / name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError("official schema hash mismatch: " + name)
            schema = json.loads(raw)
            resource = Resource.from_contents(schema)
            resources.extend((uri, resource) for uri in (schema["$id"], schema["$id"].replace("http:", "https:")))
            if name.startswith("bom-"):
                root_schema = schema
        validator = jsonschema.Draft7Validator(root_schema, registry=Registry().with_resources(resources))
        failures.extend("schema: " + str(e) for e in validator.iter_errors(cdx))
    except Exception as exc:
        failures.append("schema unavailable/invalid (offline only): " + str(exc))
    if cdx.get("specVersion") != "1.6" or cdx.get("bomFormat") != "CycloneDX":
        failures.append("expected CycloneDX 1.6")

    def flatten(items):
        return [item for c in items for item in [c] + flatten(c.get("components", []))]

    components = flatten(cdx.get("components", []))
    root = cdx.get("metadata", {}).get("component", {})
    packages = native.get("artifacts", [])
    if not components or not packages or not root.get("name") or not root.get("bom-ref"):
        failures.append("nonempty root and native/CDX components required")
    refs = [c.get("bom-ref") for c in [root] + components]
    if None in refs or len(refs) != len(set(refs)):
        failures.append("missing or duplicate bom-ref")
    for dep in cdx.get("dependencies", []):
        for ref in [dep.get("ref")] + dep.get("dependsOn", []) + dep.get("provides", []):
            if ref not in refs:
                failures.append("unresolved dependency target: " + str(ref))
    ids = {p["id"]: p for p in packages}
    if len(ids) != len(packages):
        failures.append("duplicate native package id")
    seen = set()
    for component in components:
        ref = component.get("bom-ref", "")
        pid = parse_qs(urlsplit(ref).query).get("package-id", [None])[0]
        if pid is None:
            continue
        seen.add(pid)
        p = ids.get(pid)
        name = "/".join(filter(None, (component.get("group"), component.get("name"))))
        if p is None or (name, component.get("version"), component.get("purl")) != (
            p.get("name"),
            p.get("version"),
            p.get("purl"),
        ):
            failures.append("native/CDX package mismatch: " + ref)
    if seen and seen != set(ids):
        failures.append("native/CDX package-id sets differ")
    for edge in native.get("artifactRelationships", []):
        if edge["type"] == "dependency-of" and (edge["parent"] not in ids or edge["child"] not in ids):
            failures.append("unresolved native package dependency: " + json.dumps(edge))
    return {
        "component_types": dict(Counter(c.get("type") for c in components)),
        "relationship_types": dict(Counter(e["type"] for e in native.get("artifactRelationships", []))),
        "unknown_versions": [p["id"] for p in packages if not p.get("version")],
        "unknown_licenses": [p["id"] for p in packages if not p.get("licenses")],
        "id_consistency": "supported package-id references" if seen else "unsupported: no package-id references",
    }


def locations(package):
    return sorted({p["path"].removeprefix("/").removeprefix("./") for p in package.get("locations", [])})


def normalized_name(name, ecosystem):
    return re.sub(r"[-_.]+", "-", name).lower() if ecosystem == "python" else name.lower()


def reconcile(snapshot, manifest, native, failures):
    """Reconcile each lock record without collapsing origin or namespace variants."""
    coverage = {
        "view": "source-union, not installed; alternatives are not selected profiles",
        "inputs": [],
        "missing": [],
        "ambiguities": [],
        "unsupported": [],
    }
    files = manifest.get("files", [])
    paths = [f["path"] for f in files]
    if "uv.lock" not in paths:
        failures.append("missing root lock: uv.lock")
    if not any(p.endswith("package-lock.json") for p in paths):
        failures.append("missing root npm package-lock.json")
    if len(paths) != len(set(paths)):
        failures.append("duplicate input manifest path")
    for f in files:
        path = f["path"]
        evidence = [p for p in native.get("artifacts", []) if path in locations(p)]
        report = {
            "path": path,
            "scope": f.get("scope"),
            "disposition": "partial",
            "evidence": [{"id": p["id"], "locations": p.get("locations", [])} for p in evidence],
            "entries": [],
            "limitations": [],
        }
        coverage["inputs"].append(report)
        try:
            base = snapshot / ("inputs" if f.get("scan") else "context")
            target = base / path
            if (
                Path(path).is_absolute()
                or ".." in Path(path).parts
                or not target.resolve().is_relative_to(base.resolve())
            ):
                raise ValueError("unsafe captured input path")
            raw = target.read_bytes()
            if hashlib.sha256(raw).hexdigest() != f["sha256"] or len(raw) != f["bytes"]:
                failures.append("input hash/size mismatch: " + path)
            if not f.get("scan"):
                report.update(disposition="manual", limitations=["Context only; not scanner input."])
                continue
            if Path(path).name == "uv.lock":
                data = tomli.loads(raw.decode())
                entries = [(str(i), p, "python") for i, p in enumerate(data.get("package", []))]
            elif Path(path).name == "package-lock.json":
                data = json.loads(raw)
                if "packages" not in data:
                    raise ValueError("unsupported npm lock without packages map")
                entries = [(k, p, "npm") for k, p in data["packages"].items()]
            else:
                license_file = any(t in Path(path).name.upper() for t in ("LICENSE", "LICENCE", "NOTICE", "COPYING"))
                report.update(
                    disposition="not-package-metadata" if license_file else "partial",
                    limitations=[
                        "License evidence only; not dependency-license attribution."
                        if license_file
                        else "Manifest/requirements/setup declaration not fully reconciled; no execution or resolution."
                    ],
                )
                continue
            if not entries:
                failures.append("empty lock package entries: " + path)
            for key, entry, ecosystem in entries:
                inferred = key.rsplit("node_modules/", 1)[-1] if key else data.get("name", "")
                name = entry.get("name", inferred)
                record = {
                    "path": path,
                    "entry": key,
                    "name": name,
                    "version": entry.get("version"),
                    "source": entry.get("source", entry.get("resolved")),
                    "lock_record": entry,
                }
                unsupported = ecosystem == "npm" and (
                    entry.get("link")
                    or (key and "node_modules/" not in key)
                    or (key and entry.get("name", inferred) != inferred)
                    or str(entry.get("version", "")).startswith("npm:")
                )
                candidates = [
                    p
                    for p in evidence
                    if p.get("type") == ecosystem
                    and normalized_name(p["name"], ecosystem) == normalized_name(name, ecosystem)
                    and p.get("version") == entry.get("version")
                ]
                record["matched_ids"] = [p["id"] for p in candidates]
                record["status"] = "matched"
                if unsupported:
                    record["status"] = "unsupported"
                    coverage["unsupported"].append(record)
                elif not candidates:
                    record["status"] = "missing"
                    coverage["missing"].append(record)
                    failures.append("missing lock package: " + path + "#" + key + " " + name)
                else:
                    source = entry.get("source", {})
                    expected = next(iter(source.values()), None) if ecosystem == "python" else entry.get("resolved")
                    origins = [
                        p.get("metadata", {}).get("index" if ecosystem == "python" else "resolved") for p in candidates
                    ]
                    if (
                        len(candidates) != 1
                        or (expected is not None and expected not in origins)
                        or any(k in source for k in ("git", "path", "editable"))
                        or entry.get("resolution-markers")
                    ):
                        record["status"] = "ambiguous"
                        record["reason"] = (
                            "origin/profile not uniquely established; identity/location candidate is not installed"
                            " evidence"
                        )
                        coverage["ambiguities"].append(record)
                report["entries"].append(record)
            report["disposition"] = "matched" if all(r["status"] == "matched" for r in report["entries"]) else "partial"
            report["limitations"] = [
                "Source union only; optional groups/platform selections and installed state not established.",
                "Dependency graph completeness and license attribution are not established by identity reconciliation.",
            ]
        except Exception as exc:
            report["limitations"].append(str(exc))
            failures.append("input " + path + ": " + str(exc))
    return coverage


def normalized_inventory(native):
    """Return deterministic package identities and dependency edges, not run/root IDs."""

    def stable(value):
        if isinstance(value, dict):
            return {k: stable(v) for k, v in value.items() if k.lower() not in ("timestamp", "builddate")}
        if isinstance(value, list):
            return sorted((stable(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
        return value

    packages = {p["id"]: stable({k: v for k, v in p.items() if k != "id"}) for p in native.get("artifacts", [])}
    edges = [
        {
            "dependency": packages.get(e["parent"], {"unresolved": e["parent"]}),
            "dependent": packages.get(e["child"], {"unresolved": e["child"]}),
            "metadata": e.get("metadata"),
        }
        for e in native.get("artifactRelationships", [])
        if e["type"] == "dependency-of"
    ]
    return stable({"packages": list(packages.values()), "dependencies": edges})


def root_declarations(snapshot, manifest, native):
    """Expose root manifest/lock drift without resolving groups, markers or dependencies."""
    selected = {f["path"] for f in manifest["files"] if f.get("scan")}
    if not {"pyproject.toml", "uv.lock"} <= selected:
        return []
    project = tomli.loads((snapshot / "inputs/pyproject.toml").read_text())
    lock = tomli.loads((snapshot / "inputs/uv.lock").read_text())
    root_name = normalized_name(project.get("project", {}).get("name", ""), "python")
    locked_declarations = {
        normalized_name(r["name"], "python")
        for p in lock.get("package", [])
        if normalized_name(p["name"], "python") == root_name
        for r in p.get("metadata", {}).get("requires-dist", [])
    }
    groups = {"project.dependencies": project.get("project", {}).get("dependencies", [])}
    groups.update({"extra:" + k: v for k, v in project.get("project", {}).get("optional-dependencies", {}).items()})
    groups.update({"group:" + k: v for k, v in project.get("dependency-groups", {}).items()})
    records = []
    for group, declarations in groups.items():
        for declaration in declarations:
            if not isinstance(declaration, str):
                continue  # Include-group references are retained in the captured manifest; no selection here.
            requirement = Requirement(declaration)
            name = normalized_name(requirement.name, "python")

            def compatible(package):
                if normalized_name(package["name"], "python") != name:
                    return False
                try:
                    return requirement.specifier.contains(Version(package.get("version", "")), prereleases=True)
                except InvalidVersion:
                    return False

            lock_candidates = [p for p in lock.get("package", []) if compatible(p)]
            candidates = [p for p in native.get("artifacts", []) if p.get("type") == "python" and compatible(p)]
            records.append({
                "name": name,
                "declaration": declaration,
                "group": group,
                "marker": str(requirement.marker) if requirement.marker else None,
                "lock_candidates": sorted({p["version"] for p in lock_candidates}),
                "inventory_candidates": [p["id"] for p in candidates],
                "listed_in_locked_root_requires_dist": (
                    None if group.startswith("group:") else name in locked_declarations
                ),
                "limitation": (
                    "Compatible name/version candidates only; markers, source mappings, extras and profiles are not"
                    " resolved. Root requires-dist comparison is name-only, not graph completeness."
                ),
            })
    return records


def check_collection(snapshot, manifest, native, cdx, failures):
    """Bind local collection evidence, approved input membership and source identity."""
    collection = json.loads((snapshot / "collection.json").read_text())
    scope_bytes = (snapshot / "scope.json").read_bytes()
    scope = json.loads(scope_bytes)
    if hashlib.sha256(scope_bytes).hexdigest() != collection.get("scope_sha256"):
        failures.append("recorded scope hash mismatch")
    if hashlib.sha256((snapshot / "input-manifest.json").read_bytes()).hexdigest() != collection.get(
        "input_manifest_sha256"
    ):
        failures.append("recorded input manifest hash mismatch")

    def membership(files):
        if any(type(f.get("scan")) is not bool for f in files):
            raise ValueError("scope membership requires explicit scan booleans")
        members = {(f["path"], f["scan"], f["sha256"]) for f in files}
        if len(members) != len(files) or len({f["path"] for f in files}) != len(files):
            raise ValueError("duplicate scope membership")
        return members

    if membership(scope["files"]) != membership(manifest["files"]):
        failures.append("approved scope membership differs from input manifest")
    if collection.get("scan_completed") is not True or collection.get("original_inputs_unchanged") is not True:
        failures.append("collection did not complete with unchanged originals")
    commands = collection.get("commands", [])
    if not any(c.get("name") == "scan" and c.get("exit") == 0 for c in commands) or any(
        c.get("exit") != 0 for c in commands
    ):
        failures.append("collection commands do not record a successful scan")
    expected = (collection.get("source_name"), collection.get("root_commit"))
    source = native.get("source", {})
    root = cdx.get("metadata", {}).get("component", {})
    if (
        not all(expected)
        or (source.get("name"), source.get("version")) != expected
        or (root.get("name"), root.get("version")) != expected
    ):
        failures.append("SBOM source identity differs from collection subject")
    for suffix in ("syft", "cdx"):
        relative = f"source/repository.{suffix}.json"
        if hashlib.sha256((snapshot / relative).read_bytes()).hexdigest() != collection.get("output_sha256", {}).get(
            relative
        ):
            failures.append("recorded scanner output hash mismatch: " + relative)


def validate(snapshot, schemas):
    """Write reports alongside unmodified scanner outputs; return both reports."""
    snapshot = Path(snapshot)
    validation = {"ok": True, "failures": []}
    native, manifest = {}, {"files": []}
    try:
        manifest = json.loads((snapshot / "input-manifest.json").read_text())
    except Exception as exc:
        validation["failures"].append("input manifest: " + str(exc))
    try:
        native = json.loads((snapshot / "source/repository.syft.json").read_text())
        cdx = json.loads((snapshot / "source/repository.cdx.json").read_text())
        validation["summary"] = check_bom(native, cdx, schemas, validation["failures"])
        check_collection(snapshot, manifest, native, cdx, validation["failures"])
    except Exception as exc:
        validation["failures"].append("scanner output: " + str(exc))
    try:
        coverage = reconcile(snapshot, manifest, native, validation["failures"])
        coverage["root_declarations"] = root_declarations(snapshot, manifest, native)
        coverage["declaration_gaps"] = [
            r for r in coverage["root_declarations"] if not r["lock_candidates"] or not r["inventory_candidates"]
        ]
        coverage["root_lock_metadata_drift"] = [
            r for r in coverage["root_declarations"] if r["listed_in_locked_root_requires_dist"] is False
        ]
    except Exception as exc:
        validation["failures"].append("reconciliation/input manifest: " + str(exc))
        coverage = {"view": "source-union, not installed", "inputs": [], "error": str(exc)}
    validation["ok"] = not validation["failures"]
    validation["ok_scope"] = (
        "Schema, references, captured hashes and identities already enumerated by lockfiles; NOT complete source"
        " coverage."
    )
    validation["source_coverage_complete"] = False
    validation["tooling"] = {name: version(name) for name in ("jsonschema", "tomli", "packaging", "referencing")}
    validation["validator_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for name, report in [("validation", validation), ("coverage", coverage)]:
        (snapshot / (name + ".json")).write_text(json.dumps(report, indent=2) + "\n")
    return validation, coverage


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--schemas", required=True, type=Path)
    args = parser.parse_args()
    result, _ = validate(args.snapshot, args.schemas)
    raise SystemExit(0 if result["ok"] else 1)
