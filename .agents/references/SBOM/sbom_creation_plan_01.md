# IsaacLab-Arena SBOM creation plan 01

Status: S0/S1 executed; S2 source collection, structural validation and coverage report delivered with explicit coverage gaps. S3–S6 remain unexecuted. This is not complete source coverage or installed-runtime acceptance. See the [runbook](RUNBOOK.md) for commands, current artifact paths, findings and retention.

Prepared: 2026-09-18. This is the canonical SBOM plan in this directory. The original request was documentation-only; the subsequent request to proceed authorized the recommended first source milestone and its bounded tooling acquisition. Private state, image downloads/builds, CI changes and publication remain outside execution scope. Workflow-refactoring implementation remains on hold; its status stays in the [existing implementation handoff](../plans/dashboard_cli_workflow_parity/research-stack-implementation-handoff.md).

Execution checkpoint: the verified source snapshot is `outputs/sbom/20260918T234038Z-83cc62b90a1f/`. Paired offline scans produced identical normalized inventories; official schema, source/scope bindings, captured hashes and existing lock entries passed validation. Root declarations for Shapely, Neo4j and Uvicorn lack compatible locked/scanned candidates. Source/profile ambiguities, unknown license metadata and partially parsed declarations remain documented, not waived. No project dependency or lockfile was changed to conceal those gaps. The report and reusable tooling do not require application architecture changes.

## 1. Outcome and terminology

Create a traceable, machine-readable inventory of the software used by this repository and selected builds/deployments. Each artifact must identify its subject, collection method, scope, unresolved coverage and source evidence.

An SBOM is an inventory, not a security certificate, proof of reproducibility, legal opinion or guarantee that every component was detected. A vulnerability report and a VEX/exploitability assessment are separate artifacts. A model/checkpoint inventory is related provenance, not automatically covered by a software-package scan.

The first deliverable is a **source-dependency baseline and coverage report**. It must not claim to enumerate the installed robotics runtime or the complete deployed stack. Subsequent deliverables add profile-specific dependencies, exact-image inventories, frontend build provenance and explicitly authorized deployment/research-artifact records.

Completion is per declared subject/profile, not a single unqualified “repository fully covered” badge.

## 2. Observed repository baseline

S0 execution discovery refreshed the earlier planning context:

- Root: `/workspaces/IsaacLab-Arena`; branch: `dev/0.3.0-prerelease`.
- Collected HEAD: `83cc62b90a1fc995b89f2e5b6050600a52822f66`. The earlier workflow-context HEAD was not the collection subject.
- The working tree was clean before this execution; added SBOM tooling makes the captured checkout dirty. The collection records dirty state and exact input hashes and remains a development snapshot, not a clean release of HEAD.
- Root project metadata declares `isaaclab_arena` version `0.3.0`, Python `>=3.12,<3.13`, and Apache-2.0 for the project. This does not assign that license to dependencies or assets.
- `uv.lock` contains alternative `isaaclab-from-source` and `isaaclab-from-wheel` resolutions; the root uv configuration targets Linux x86_64. Docker installs are not simply a synchronization of this lockfile.
- `web/arena-workbench/package-lock.json` provides the npm resolution; its manifest separates dependencies from development dependencies.
- Top-level submodule checkouts: IsaacLab `ffff603eafc6b74264a5261cc0183d6a65390d78`; Isaac-GR00T `7b8f37ec16763df6765768f0e0ef692a357870af`. Recursive discovery recorded nine initialized submodules and one uninitialized nested gitlink; captured scope retains their identities without fetching or updating them.
- Syft 1.46.0 was acquired into the ignored local tooling cache and its archive/checksum signature verified. It was not installed globally. See retained acquisition evidence and the runbook for the verifier bootstrap limitation.

Recheck this baseline before collection. Do not reset, stage, commit, resolve dependencies or update submodules to make the inventory easier.

## 3. Coverage and source map

Paths in the table are repository-relative. They are discovery entry points, not a claim that all nested dependencies have already been audited.

| Layer / subject | Existing inputs | Required treatment |
| --- | --- | --- |
| First-party Python | `pyproject.toml`, `uv.lock`, packaged `isaaclab_arena*` trees | Root/package identities, declared constraints, resolved packages, extras/groups and local/editable sources; distinguish importable packages from independent distributions |
| Frontend source | `web/arena-workbench/package.json`, `web/arena-workbench/package-lock.json` | npm packages, integrity/source metadata, dependency relationships, production/dev/optional distinctions |
| IsaacLab and GR00T source | `.gitmodules`, `submodules/IsaacLab`, `submodules/Isaac-GR00T` | Inventory their own manifests/license evidence; identify exact fork and revision, not an inferred upstream tag or version alone |
| Arena runtime image | `docker/Dockerfile.isaaclab_arena`, `docker/docker-compose.sim.yml`, referenced setup/install scripts | Final installed Python, OS and native components; base image, effective build arguments, editable installs and Git-based dependencies |
| Frontend build/dev/production | `docker/workbench/Dockerfile.frontend`, related compose definitions, lockfile and built assets | Separate Node/build tools and dev image from the Nginx production image; link bundled JavaScript provenance to actual build outputs |
| Policy integrations | `isaaclab_arena_gr00t/docker/Dockerfile.gr00t_1_6`, `isaaclab_arena_dreamzero/docker/Dockerfile`, `isaaclab_arena_openpi/docker/OPENPI_COMMIT`, `docker/setup/install_cuda.sh` | Per-selected-integration inventory; discover additional recipes/pins and optional cuRobo/CUDA paths without enabling them |
| Development and documentation | `.devcontainer/Dockerfile`, `.devcontainer/docker-compose.test.yml`, `docs/requirements.txt`, development/test tooling | Separate development/build inventories; do not describe their complete dependency sets as production-shipped software |
| Installed deployment overlay | Approved image IDs plus bind-mounted source, dependency volumes and writable-layer changes | Later, explicitly scoped inventory; an image SBOM does not include every mounted or subsequently installed component |
| Models, datasets and USD assets | Approved manifests, model revisions, asset/source receipts and artifact hashes | Separate linked research-artifact inventory; do not recursively scan weights/datasets or infer loaded policy identity from installed package names |
| External prerequisites/services | Host GPU driver, selected Neo4j/policy service, remote model provider | Record scoped external dependencies separately. A remote provider name does not reveal its internal software inventory |

Important observed differences:

- The Arena Dockerfile uses an overridable Isaac Sim base, apt installations, pip/editable installs, a pinned OpenPI Git source and optional cuRobo/CUDA installation. Lockfile coverage alone cannot attest the resulting image.
- The frontend production stage copies `dist/` into Nginx. Its npm manifest and `node_modules` need not be present in that image; retain the frontend dependency/build record rather than expecting an image scan to rediscover every bundled library.
- A base-image tag or compose tag is a build/deployment selector, not an immutable image identity. Dockerfile declarations are not evidence that a particular build argument or optional integration was used.

## 4. Inventory views and profile rules

Maintain separate, linked views:

1. **Repository source baseline:** approved current manifests/lockfiles and submodule metadata. It may include alternative resolutions, explicitly labelled as such.
2. **Selected dependency profile:** only packages selected for a documented installation flavor, platform, Python version, extras and groups. Native uv source/wheel flavors are separate profiles; actual Docker builds are a separate subject.
3. **Built image:** packages detected in one exact platform image. Distinguish a multi-platform index digest, selected platform manifest digest and local image/config ID where available; do not silently interchange them.
4. **Frontend build/release:** source dependency/build-tool inventory linked to source inputs, output hashes and the production image. Lockfile presence is not proof that every package was bundled or shipped.
5. **Observed deployment overlay:** explicitly approved differences from image contents, with observation time and collection limits.
6. **Research-artifact inventory:** checkpoint/dataset/asset identities, origin and license evidence, linked to the software subject without asserting those files are ordinary installed libraries.

Do not deduplicate only by component name. Preserve ecosystem, version, origin/fork, artifact hashes, profile/platform and relevant package qualifiers. The same name/version can represent different source builds or wheels. Use PURLs where valid and supported; retain honest source references when an exact package identity cannot be established.

Record relationships only when evidenced. Label declared requirements, resolved dependency edges, installed-package evidence and build/runtime relationships distinctly. Unknown edges remain unknown; a flat package list does not prove a complete dependency graph.

## 5. Tool and format decision

Recommended default:

- **Syft** for directory/manifest and image package discovery.
- **CycloneDX JSON**, with an explicitly selected supported schema version (proposed baseline: 1.6), as the primary exchange artifact.
- **Syft native JSON** from the same scan to preserve richer scanner evidence.
- **SPDX JSON** (proposed interoperability target: 2.3) only when required by a consumer; emit from the original scan where possible and check conversion losses.
- A pinned standards validator for format checks. JSON parsing alone is not schema validation.
- **Grype** as the default later vulnerability consumer; Trivy is an alternative, not an additional mandatory scanner.

Pin the scanner release/artifact, checksum, provenance verification method, configuration and format versions. Verify official signatures/attestations when available; a checksum downloaded beside a binary alone is not independent publisher authentication. Install in an isolated tooling location, not the Arena environment or the user's unrelated Python installation. No application dependency installation is needed to parse lockfiles.

Before choosing catalogers, verify the pinned tool's real `uv.lock` and npm lockfile support, dependency-edge preservation and behavior with mutually exclusive groups. Do not assume a successful scan parsed every format. If profile selection or a lockfile is unsupported, use a reviewed ecosystem-native export/adapter against frozen inputs, without re-resolution or application installation, and retain its input/output hashes and limitations. Do not create a custom SBOM framework merely to fill missing metadata.

Scanner acquisition and any metadata enrichment are separate network actions. Collection should be offline by default; explicitly disable update/enrichment behavior and verify the selected tool configuration. Tool installation or use must not automatically build images, run package lifecycle hooks, import Arena code or launch services.

## 6. Safe collection boundary

For the first source pass, build a reviewed allowlisted snapshot containing manifests, lockfiles, selected license/notice files and first-party/submodule identity metadata. Preserve relative source locations and hash the captured input bytes. Record whether license analysis is manifest-only or also includes approved source evidence.

Exclude private or irrelevant material by construction, rather than relying only on a broad recursive scanner exclusion list:

- Credentials and credential files, `.env` variants, `.npmrc`, `.pypirc`, `.netrc`, SSH material and private configuration/state.
- `.git` internals, caches, virtual environments, `node_modules`, build outputs, experiment outputs and prior generated SBOMs from the source-manifest pass. Installed dependencies/build outputs belong only in their deliberately selected later views.
- Model weights, datasets, recordings and research database contents unless separately selected for a later inventory.
- Unreviewed symlink targets, remote mounts and unrelated host directories.

Approved manifests and package URLs can themselves contain private endpoints or embedded authentication. If encountered, stop publication/collection of the affected input and report a sanitized blocker; do not echo secrets. Any operator-approved redacted derivative must be identified as a derivative, not passed off as the original lockfile.

For images, prefer an explicit local immutable image or approved OCI/Docker archive. No implicit registry pull, container start or application entrypoint execution. Do not extract arbitrary image file contents into reports. Review metadata/location disclosure before publication. Full image/archive scans can be large: establish disk, memory, time and temporary-storage bounds before starting them.

Do not query running containers, export their writable layers, scan dependency volumes or inventory the host as a side effect of an image scan. Those are separate approved subjects. Shared research services and queues remain untouched.

## 7. Evidence and artifact layout

Proposed generated outputs, created only during the execution phases:

```text
outputs/sbom/<snapshot-id>/
  collection.json
  source/
    repository.cdx.json
    repository.syft.json
  profiles/<profile-id>/
    dependencies.cdx.json
    dependencies.syft.json
  images/<image-subject-id>/
    image.cdx.json
    image.syft.json
  frontend/<build-id>/
    build-linkage.json
  coverage.md
  validation.json
  checksums.sha256
  # Later, only for approved scopes:
  research-artifacts.json
  vulnerabilities/<subject-id>.json
```

Confirm ignore/retention behavior before generating files; the path is proposed, not currently created. Keep large/generated SBOMs and local scan evidence outside source commits by default. For releases, attach reviewed artifacts to the release/image subject. Do not concatenate SBOM JSON or claim a merged inventory is complete merely because duplicate names were removed.

`collection.json` must record:

- Logical subject and view, snapshot ID, UTC collection interval and completion/failure status.
- Root commit/branch; clean/dirty state; submodule gitlinks, checked-out SHAs and dirty/missing status. For a working-tree subject, record a scoped source fingerprint or an explicit limit to dependency-input identity; never imply the commit alone represents uncommitted code.
- Input-file hashes and source-relative locations; selected profiles/groups/extras, platform and language/runtime constraints.
- Scanner version/binary or image digest, configuration hash, catalogers actually used, command and exit status; approved network behavior.
- Exact image/platform/build subject and known build arguments, without secrets. Mark unavailable build provenance as unknown rather than reconstructing a historical build from today's Dockerfile.
- Coverage exclusions, unresolved identities/versions/licenses/relationships, warnings, validation results and output digests.

Record field provenance: a lockfile's artifact hash is a recorded expected hash, not evidence that the referenced wheel was downloaded and verified. A package-manager record is evidence of installation metadata, not proof that every installed byte is intact. A generated SBOM hash protects artifact integrity; it does not authenticate its origin unless a later signing/attestation step does so.

## 8. Phased work packages and exit gates

All execution phases are **not started**. Source discovery used to draft this plan is not an SBOM scan. Each role is a responsibility, not a new service or framework.

| Phase | Work | Responsible role | Exit evidence |
| --- | --- | --- | --- |
| S0 — freeze collection scope | Recheck checkout; inventory dependency inputs across first-party, submodules, optional integrations and build recipes; choose first source subject and profile matrix; agree output/privacy/resource bounds | Coordinator with repository owner | Reviewed input/target matrix; omissions explicit; no ambiguous “installed” claim for a universal lockfile |
| S1 — admit tooling | Select/pin scanner and validators; verify provenance; test catalogers on small Python/npm fixtures and actual approved lockfiles; decide profile-export fallback only if necessary | Tooling owner | Exact commands/configuration and supported formats recorded; no project install, lockfile rewrite or unexpected network access |
| S2 — source baseline | Capture allowlisted inputs; inventory Python/npm declarations and locked identities, root packages and submodule revisions; emit CycloneDX/native outputs and coverage report | Collection owner | Schema-valid artifacts with known root subjects; programmatic input/output reconciliation; alternative groups and dev/build scopes labelled; unresolved items enumerated |
| S3 — selected profiles and frontend build linkage | Produce per-profile resolution inventories; connect first-party/submodule identities; bind existing build outputs when available, or leave build linkage pending | Python/frontend owners | No mixing of mutually exclusive profiles; existing lockfiles unchanged; frontend build dependencies not falsely labelled bundled; source/output hashes linked |
| S4 — exact image inventories | Select approved existing image/platform identities; scan Arena, frontend and chosen policy/database/development images separately; reconcile recipe declarations and installed findings | Runtime inventory owner | Per-image validated SBOMs, exact immutable subjects, base/native/OS coverage and documented gaps; no service start or assumed tag equivalence |
| S5 — deployment and research provenance | Inventory only explicitly approved overlays, host prerequisites, checkpoints/assets/datasets or remote-service declarations | Runtime/research owner | Distinct observed/declared/unknown states, origin and license evidence, no unapproved private-state reads or unsupported loaded-model claim |
| S6 — consume findings | Run vulnerability analysis with a dated/pinned database; review license gaps and actionable results; add VEX only with evidence-backed adjudication | Security/license reviewer | Separate subject-bound reports; false positives and unknowns retained; no claim of exploitability or license clearance from package presence alone |
| S7 — automate and distribute | After local acceptance, propose scripts/runbook and CI/release integration; sign/attest and publish only to an approved destination | Maintainer/release owner | Re-runnable commands, reproducible input identity, SBOM diff review and release linkage; CI/signing/publication separately authorized |

First milestone: S0–S2 only, producing a source baseline with honest limitations. Do not make full deployment or ML artifact inventory a prerequisite for this useful first deliverable.

S3 and S4 may proceed independently once their subjects are approved. S5–S7 are not required to declare the initial source baseline complete, and that baseline never implies those later subjects are covered.

## 9. Acceptance checklist

### Source baseline

- [ ] Root/project version and snapshot identity match captured metadata; dirty source is not labelled a clean release.
- [ ] Root Python and frontend lockfile inputs are represented; both submodule identities are recorded and their manifest coverage is explicit.
- [ ] Optional integrations, dependency groups/extras and development/build tooling are included in the scope matrix or explicitly deferred.
- [ ] Exact locked versions, declared ranges and unresolved versions remain distinguishable.
- [ ] No union of alternative uv resolutions is described as one installed environment.
- [ ] Each approved input is accounted for as supported-and-parsed, deliberately excluded or unsupported/failed. Reconcile counts and identities programmatically, not by visually checking a few familiar names.
- [ ] CycloneDX schema validation passes; root references, dependency targets and component identifiers resolve. An empty scan cannot pass just because it emitted valid JSON.
- [ ] Expected sentinel components from actual inputs appear in the appropriate scope (for example Pydantic/OpenAI/Neo4j and React/Three.js); these checks supplement, not replace, full input reconciliation.
- [ ] Missing license/supplier/native metadata and dependency relationships appear in the coverage report. No guessed values fill gaps.
- [ ] A rerun over identical captured inputs produces the same normalized component/relationship inventory; timestamps/serial IDs may legitimately differ.
- [ ] No application code, package installer, model call, simulator, service or queue was executed; no unexpected outbound enrichment occurred.
- [ ] Outputs are locally reviewed for private URLs, paths and credential disclosure before sharing.

### Image/build and later views

- [ ] Immutable subject/platform identity is verified; an unavailable selected image blocks that inventory rather than silently pulling/substituting another tag.
- [ ] Source/lockfile findings and installed-image findings are separated and discrepancies explained.
- [ ] Compiled frontend software has build/source linkage; a bare Nginx package list is not presented as its full application inventory.
- [ ] Host drivers, runtime-mounted dependencies, proprietary/native components and optional integrations have evidence or explicit coverage gaps.
- [ ] Research assets and externally hosted services are separately scoped; no internal provider software or serving checkpoint identity is invented.
- [ ] Vulnerability reports identify both their SBOM subject and database snapshot/date. Signing/publication, when enabled, binds the actual output digest to the exact release subject.

## 10. Required decisions and approval boundaries

Proposed defaults: source baseline first; current working tree labelled as a development snapshot; CycloneDX plus Syft JSON; offline collection; no image builds, package installs, source upload or publication.

Before S1/S2 execution, confirm scanner acquisition/version/provenance and the approved source snapshot/output location. The present plan-writing request does not authorize installing a scanner.

Before S3/S4, select the installation profiles and exact images/builds. Read-only image collection is not permission to pull/build images, run their entrypoints or inspect private runtime mounts. Existing permission for disposable Neo4j tests is not SBOM collection authority for a research database/container.

Before S5, explicitly select any deployment overlays, host metadata or large/private research artifacts. Before S7, approve changes under `.github/workflows/` or `docker/`, signing-key use and the publication destination. No commit/push is implied by any collection approval.

Normal fixes to collection scripts and isolated fixture checks can proceed within an approved execution scope without repeated approval. Missing tool capability or a scanner/test defect is engineering work, not an excuse to fabricate inventory or weaken acceptance.

## 11. Review and maintenance

Use one bounded independent review of this plan for coverage, profile semantics and collection side effects; adjudicate findings against source. During execution, test the real scanner on fixtures and captured inputs, then independently check coverage rather than accepting its exit code alone.

Keep this document as the plan/status owner for SBOM work. Record phase results and artifact locations here, with large/raw evidence under the selected output location. Add a concise collection runbook when commands have actually been exercised. Do not create competing current plans or modify the workflow-refactoring plan as part of SBOM collection.

Regenerate or reassess the relevant view when lockfiles, submodule revisions, selected build arguments/base images, built frontend assets, installed overlays or release subjects change. Vulnerability database refreshes can change a vulnerability report without changing the SBOM. A source-only implementation edit may leave dependency components unchanged but still requires accurate subject identity.

## 12. References and verification boundary

- [Root project manifest](../../../pyproject.toml) and [uv lockfile](../../../uv.lock).
- [Frontend manifest](../../../web/arena-workbench/package.json) and [npm lockfile](../../../web/arena-workbench/package-lock.json).
- [Git submodule declarations](../../../.gitmodules).
- [Arena image recipe](../../../docker/Dockerfile.isaaclab_arena), [stack recipe](../../../docker/docker-compose.sim.yml) and [frontend image recipe](../../../docker/workbench/Dockerfile.frontend).
- [CISA SBOM overview](https://www.cisa.gov/sbom).
- [CycloneDX SBOM capabilities](https://cyclonedx.org/capabilities/sbom/).
- [Syft getting started](https://oss.anchore.com/docs/guides/sbom/getting-started/), [catalogers](https://oss.anchore.com/docs/guides/sbom/catalogers/), [formats](https://oss.anchore.com/docs/guides/sbom/formats/) and [CLI reference](https://oss.anchore.com/docs/reference/syft/cli/).

This plan is grounded in repository metadata/build-source inspection and official documentation. No scanner capability test, SBOM schema validation, image scan, vulnerability scan, runtime inventory or license clearance has occurred. Documentation checks and plan review must be reported separately from those future execution gates.

### Planning review disposition

A bounded independent source review on 2026-09-18 approved the plan's scope with no blocking findings. It confirmed the source/profile/image distinctions, frontend bundle caveat, submodule identities and useful source-only first milestone. Scanner/cataloger compatibility, nested manifest coverage, dependency-edge preservation, native-binary detection and historical build provenance remain execution-time unknowns. Review approval does not authorize or establish collection.

Scoped documentation hooks, local-link resolution, phase-ID ordering and Markdown fence checks passed. No application tests, scanners or runtime services were executed for this planning task.
