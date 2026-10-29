# Source SBOM runbook

## Current result and boundary

**Paused for study and scope review.** The user's goal is understanding project software and licenses for later delivery. These commands reproduce a preliminary inventory, not a delivery/license assessment. Read the [canonical plan](sbom_creation_plan_01.md), especially §1 and §13, before further execution; this runbook is not authority to resume scans or dependency changes.

The first source inventory has been collected with pinned Syft 1.46.0. It is **not a complete source or installed-runtime inventory**. Read the generated coverage report before using the component list.

Current verified development snapshot:

```text
outputs/sbom/20260918T234038Z-83cc62b90a1f/
```

Start with `coverage.md`; primary SBOM: `source/repository.cdx.json`. Native scanner output: `source/repository.syft.json`. Machine-readable diagnostics: `coverage.json`, `validation.json`, `verification.json`. Selection and provenance: `scope.json`, `collection.json`, `input-manifest.json`, `tool-provenance.json`, `checksums.sha256`.

Earlier `20260918T231153Z-83cc62b90a1f` collections predate the strengthened collection-binding checks and are superseded, not release evidence.

This is host tooling only: it does not import Arena, install project dependencies, resolve locks, initialize submodules, inspect images, start services, access the graph, run simulation/inference, or publish anything. Linux network-namespace support is mandatory for collection; isolation failure has no online fallback. Do not elevate privileges or change host namespace policy automatically on another machine.

## Tools and admission

This workspace already has the admitted tools in `outputs/sbom/tooling/`; nothing was installed globally or added to the application environment. No tool or package download occurs inside the collector, validator or fixture helper.

- Syft: `1.46.0`, Linux amd64. Archive SHA-256: `d654f678b709eb53c393d38519d5ed7d2e57205529404018614cfefa0fb2b5ca`.
- Extracted Syft binary SHA-256: `574df1a0862ff88ad933be214e81069e35b17618a13e019f8f1c84fe063222a2`; enforced by collection/fixture helpers.
- Official release: https://github.com/anchore/syft/releases/tag/v1.46.0. Download the Linux amd64 archive plus `syft_1.46.0_checksums.txt`, `.txt.sig`, and `.txt.pem`; the published `.pem` is base64-encoded and must be decoded before passing to Cosign. Verify archive checksum, extract only the regular `syft` member, and verify the checksum signature before executing Syft.
- Signature verifier used: Cosign `3.1.3`; official Linux amd64 asset SHA-256: `4629c757b7618056f8ddd7e2625ae9fdd94c0372a65049520bc7d9df9efc7f71`. Bootstrap was official HTTPS + GitHub asset digest, not an independent signature verification of Cosign itself.
- Required Syft certificate identity: `https://github.com/anchore/syft/.github/workflows/release.yaml@refs/heads/main`.
- Required OIDC issuer: `https://token.actions.githubusercontent.com`.
- Official schemas: `bom-1.6.schema.json`, `spdx.schema.json`, `jsf-0.82.schema.json` from https://github.com/CycloneDX/specification/tree/1.6/schema, saved under `outputs/sbom/tooling/schemas/`. Their exact hashes are enforced in `scripts/sbom/validate.py`; reference resolution is local-only.
- Validation uses host Python 3.10 and existing `jsonschema==4.26.0`, `tomli==2.4.1`, `packaging==25.0`. The actual dependency versions, including `referencing`, are recorded in each validation report. These are collection-tool prerequisites, not Arena dependencies.

For a fresh machine, obtain approval for this bounded tooling acquisition, verify the same upstream artifacts, and use a separate tooling virtual environment if those validator packages are absent. Do not modify the root project lock/environment or silently substitute another scanner/version. This runbook does not install tooling automatically. Retain the acquisition URLs, hashes, actual Cosign command/result and schema identities in a `provenance.json` record; the current example is `outputs/sbom/tooling/provenance.json`.

Signature verification invocation used (with a clean, empty tool HOME):

```bash
outputs/sbom/tooling/cosign-v3.1.3 verify-blob \
  --certificate outputs/sbom/tooling/syft-1.46.0/certificate.pem \
  --signature outputs/sbom/tooling/syft-1.46.0/checksums.sig \
  --certificate-identity https://github.com/anchore/syft/.github/workflows/release.yaml@refs/heads/main \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  outputs/sbom/tooling/syft-1.46.0/checksums.txt
```

Do not disable certificate, identity or transparency checks to bypass failure. Tool verification uses public Sigstore infrastructure; repository collection itself is offline.

## Repeat the current frozen collection

Run from the repository root. `/usr/bin/python3` below is the verified host interpreter here, not Isaac Sim's Python. On another machine use the admitted tooling interpreter explicitly.

1. Review the scope before collection. The current frozen selection is `outputs/sbom/tooling/scope.json`, derived from `outputs/sbom/discovery.json`. It covers Git-tracked inputs across the root and recursively initialized submodules, not arbitrary workspace files. Its per-input hashes and submodule commits must still match.
2. Choose two **new**, non-existing snapshot directories beneath `outputs/sbom/`. Existing snapshots are never silently overwritten.
3. Run the collector twice with the same scope and tools, then the report command. The following names are examples for a new repeat, not already-created output claims.

```bash
/usr/bin/python3 scripts/sbom/collect.py \
  --scope outputs/sbom/tooling/scope.json \
  --output outputs/sbom/local-source-a \
  --syft outputs/sbom/tooling/syft-1.46.0/syft \
  --provenance outputs/sbom/tooling/provenance.json

/usr/bin/python3 scripts/sbom/collect.py \
  --scope outputs/sbom/tooling/scope.json \
  --output outputs/sbom/local-source-b \
  --syft outputs/sbom/tooling/syft-1.46.0/syft \
  --provenance outputs/sbom/tooling/provenance.json

unshare -n /usr/bin/python3 scripts/sbom/report.py \
  --snapshot outputs/sbom/local-source-a \
  --repeat outputs/sbom/local-source-b \
  --schemas outputs/sbom/tooling/schemas
```

Standalone validation:

```bash
unshare -n /usr/bin/python3 scripts/sbom/validate.py \
  --snapshot outputs/sbom/20260918T234038Z-83cc62b90a1f \
  --schemas outputs/sbom/tooling/schemas
```

Validation regenerates `validation.json` and `coverage.json`; after changing validator code or regenerating evidence, rerun `report.py` to update the checksum manifest. It does not change raw scanner outputs.

For a new dependency revision, repeat the plan's tracked-file discovery/curation rather than reusing stale hashes or weakening the checks. Scope records contain `files` with explicit `path`, Boolean `scan`, `sha256`, `kind`, `scope` and rationale; initialized `submodules` contain `path` and `commit`. Retain excluded/deferred candidates, local source mappings, profile alternatives and coverage holes. Discovery remains reviewed curation, not an automatic whole-workspace crawl. An input that moved or changed requires a new scope and snapshot.

## Tests and checks

Fixture inputs have synthetic names and are separate from repository metadata. Their scanner outputs are generated by the actual pinned Syft binary, not fabricated JSON. They and official schemas intentionally remain in the ignored tooling cache; prepare them before running the tooling tests on another checkout.

```bash
/usr/bin/python3 scripts/sbom/prepare_fixture.py
/usr/bin/python3 scripts/sbom/test_collect.py
/usr/bin/python3 scripts/sbom/test_validate.py -v
pre-commit run --files scripts/sbom/collect.py scripts/sbom/validate.py scripts/sbom/report.py scripts/sbom/prepare_fixture.py scripts/sbom/test_collect.py scripts/sbom/test_validate.py scripts/sbom/syft.yaml
git diff --check
```

The collector rejects private/traversing paths, symlink paths, nonregular/hardlinked/oversized inputs, selected credential patterns, duplicate scope entries, changed discovery hashes and output-directory reuse. Pattern checks are not a comprehensive secret audit or publication approval.

The validator checks official schema hashes/format, source identity, successful collection, exact approved scope membership, input/output hashes, package references and lock entries. Negative tests cover tampering, dropped approved context even with a recomputed manifest hash, wrong source identity even with recomputed output hashes, incomplete collection and declared-but-unlocked dependencies. Root declarations are compared without executing setup code or resolving profiles.

## Findings and next boundary

- Root declarations `shapely`, `neo4j` and `uvicorn>=0.52.4,<0.53` have no compatible locked/scanned candidates. `uvicorn` belongs to the `web` extra; the other two are base requirements. The raw scanner SBOM omits them; their unresolved declarations are preserved in `coverage.json` and called out in `coverage.md`.
- Locked root `requires-dist` metadata also lacks the current `fastapi` and `httpx` web declarations. A package present transitively does not establish the declared direct dependency edge.
- Source/profile ambiguities, missing license metadata, unparsed declarations, an uninitialized nested submodule, native build dependencies and installed/build/asset identities remain explicit limits.
- Independent review identified dropped-scope and wrong-subject acceptance gaps. Parent reproduced them with failing regressions, added binding checks, and reran the tooling tests and actual paired collection. This closes those findings, not the remaining source-coverage gaps or later plan phases.

The source baseline is delivered with qualified coverage, not a complete-stack or licensing sign-off. The next step is defining the delivery scenario and studying software/license evidence under the canonical plan—not immediately repairing locks or expanding scans. Manifest/lock maintenance and selected-profile/image inventories are later, separately scoped decisions. Do not regenerate project locks, fetch submodules, inspect private runtime overlays, scan/pull images, modify CI or publish under the pretext of repairing this collection.

## Retention

`.gitignore` already contains `*outputs/`, so generated SBOMs, reports, logs, schemas, tool binaries and captured inputs under `outputs/sbom/` are ignored. No new ignore rule is necessary. Plans/runbooks and reusable scripts/configuration are source-controlled material; current snapshot scope/data and reports are not. Ignored files are not a backup: deliberate cleanup such as `git clean -fdx` can delete them. Agree retention/export before cleanup or release publication.
