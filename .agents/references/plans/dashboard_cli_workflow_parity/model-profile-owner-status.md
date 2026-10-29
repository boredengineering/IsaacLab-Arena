# Add model profile — implemented, offline verified

- Working create-only Journal-backed workspace catalogue, authenticated/CSRF registration, immutable replay/conflict/bounds, strict v2 public metadata with legacy v1 decoding, separate explicit profile selection and memory-only key save.
- Exact policy snapshots reach settings, public/private authorization, immutable jobs, checked config, worker allowlist, agent constructor keyword forwarding and backend calls. Explicit models remain literal; all policy modes and ping ceilings are tested. User-defined profiles retain strict raw JSON/local schema validation and cannot inherit documented readiness.
- UI registration requires catalogue readback, never activates or saves a key, and fences stale form, metadata ABA, actual session replacement and unmount handlers. No service or deployment effects.

## Executed final evidence

- **340 backend cases across 8 requested files passed**, split into the required SDK-only run `arena-f0-backend-fefd0b8c3372` (60) and remaining seven files `arena-f0-backend-c11f41c8c013` (280). Both have zero forbidden counters and verified cleanup.
- **106 frontend cases passed** (66 component, 40 decoder), `arena-functional-frontend-198929d530fd`; staged owned source matches current files and authoritative cleanup is empty.
- **95 runner sandbox units passed**, `arena-core-units-336b57447041`.
- Ordinary typecheck and production build passed: `arena-f0-typecheck-ce7b3c0e8669`, `arena-f0-build-ac35b6be4ec1`. Owned tracked-path `git diff --check` passed.
- Machine-readable counts, hashes, exact run links, retained RED evidence and limitations: `model-profile-owner-evidence.json`. Shared contract: `model-profile-contract.md`.

## Closure notes

Parent's RW-bind discovery fix restored the standard runner; no shared service was stopped. Temporary exact-ID discovery wrapper was used only during that ambiguity. Auth/reauthorization fixtures now explicitly avoid renderer construction. The old auth replay test incorrectly prohibited current-secret screening; a HEAD-owned implementation overlay reproduced its failure, then the test was corrected to require screening while forbidding credential/grant resolution or issuance. Production replay semantics were unchanged.

SDK evidence uses real installed serialization with synthetic transport; worker framing uses synthetic generation/OS seams. The existing runner still forbids EnvironmentGenerationAgent construction, so its keyword forwarding is implemented in source, not claimed as live execution. No native browser, provider, GPU, deployment or complete scene-readiness claim. Frontend dependencies remain trusted mutable installed-volume input. Existing runtime deprecation and build chunk/outDir warnings remain.

No commits, environment/key reads, paid model requests, service changes, or Docker infrastructure edits by this owner. Narrow `provider_readiness.py` change rejects `user_defined` snapshots before metadata transport, including a documented model literal under an unverified policy.
