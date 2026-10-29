# V7 authoring acceptance — isolated authoring snapshot passed

## Current verified snapshot

Parent executed [arena-f0-933680638528](.runs/arena-f0-933680638528/run-proof.json) using the actual production build/API and unchanged `authoring-v1` checker. The command and strict checker passed. Parent read back the browser/API records, all 39 artifact hashes and successful cleanup, and inspected desktop/mobile screenshots.

- Actual raw YAML → supported table XYZ proposals → exact candidate validation → explicit consent/Apply → distinct fresh validation passed.
- Durable Save performed one keyed POST, followed by exact receipt GET. Save did not reopen automatically; Library selection required explicit Open and verified the saved source identity and bytes.
- Browser reload retained exact saved root/hash/origin and theme. Fresh Documents-instance readback over the private durable store also passed; neither is an API process-restart claim.
- Raw Blob downloads matched the actual pre-/post-Apply bytes. The final authored root was 453 bytes, SHA-256 `b45f237852c04003827d0f1815c3f36c0058cfd47846bb6758418b3ad9864918`.
- Both themes measured root width equal to viewport: 1440px desktop and 390px mobile. Long CodeMirror lines remained inside their own scroll region. The prior native fieldset/select root overflow did not recur.
- Exactly one allowed revision write occurred in fresh private test state. Jobs and all six forbidden counters were empty/zero; API lifespan closed, its socket disappeared, and no owned containers remained.

Evidence: [browser record](.runs/arena-f0-933680638528/evidence/browser-proof.json), [API final record](.runs/arena-f0-933680638528/evidence/api-final.json), [Library before Open](.runs/arena-f0-933680638528/evidence/authoring-library-before-open.png), [reloaded editor](.runs/arena-f0-933680638528/evidence/authoring-reloaded.png), [mobile dark](.runs/arena-f0-933680638528/evidence/authoring-390-dark.png), [desktop light](.runs/arena-f0-933680638528/evidence/authoring-1440-light.png).

This is the bounded authoring profile, not full V7/F3 parity, manual numbered research persistence, live observation reliability, GPU/rendering/physics acceptance or deployment. The shared frontend remains stopped; test-only dependency reuse is explicitly trusted mutable input. Later source changes require another acceptance run. Self-authored hashes establish artifact consistency, not authenticity.

## Preserved failed predecessor

Earlier genuine run: [arena-f0-5c915a663225](.runs/arena-f0-5c915a663225/run-proof.json).
Browser detail: [browser-proof.json](.runs/arena-f0-5c915a663225/evidence/browser-proof.json).
Final API observation: [api-final.json](.runs/arena-f0-5c915a663225/evidence/api-final.json).

## Historical production blockers, subsequently fixed

1. **Durable Save is not admitted by the actual production application.**
   The real `GET /api/health` returned HTTP 200 with capabilities
   `{"diagnostic":false,"generation":false,"preview":false}`.
   `Editor` reads `health.capabilities.durable_editor_save`, whereas the
   backend advertises `durable_editor_save` only on `/api/editor`.
   The browser therefore renders **Save revision**, not **Save durable revision**.
   The authoring driver deliberately does not click legacy Save, invent a
   health response, or substitute an API fetch for the missing UI action.
2. **Mobile document overflow:** at a 390px viewport, root `scrollWidth` is
   **423px** in both light and dark themes. Measured overflowing fieldset:
   right edge 423px, width 337px; its labels/select extend to 410.5px.
   These are outside the CodeMirror horizontal scroll region. Desktop
   `scrollWidth` is 1440px at a 1440px viewport.

Production App/Editor/API/CSS files were not changed by this acceptance work.
The failure is retained rather than relabelled successful or bypassed.

## Journey results from the failed predecessor

| Journey | Result |
| --- | --- |
| Real API document load, original source validation, edit/restore correlation | Exercised |
| Raw browser-authored supported `background / table`, explicit identity pose, no incident references, `droid_abs_joint_pos`, actual `NoTask` | Actual Arena schema valid |
| Inspector X=1.25, Y=-0.25, Z=0.125 proposals | Each separately validated with exact outbound root YAML/frozen view |
| Candidate review does not edit current YAML | Verified through real CodeMirror clipboard readback |
| Apply requires diff consent; option A→B→A retires old consent | Verified |
| Fresh validation after each Apply, distinct from equal-byte candidate validation | Verified; Save withheld while validation is pending |
| Invalid raw YAML and aborted candidate-validation transport | Invalid Save/Apply disabled; valid recovery worked; no fulfilled responses |
| Same CodeMirror node through XYZ Apply, Library navigation, dirty cancel and theme changes | Verified; prompt retained |
| Dirty Library Open cancellation | No document GET and no draft replacement |
| Actual local Blob downloads | Exact byte readback, before and after Apply |
| Desktop light/dark appearance | Measured and screenshot captured; no root overflow |
| Mobile light/dark appearance | Captured; **failed root overflow** |
| Durable Save POST → receipt GET | **Blocked by absent health capability; zero Save POSTs** |
| Library exact saved revision → explicit reopen | **Blocked downstream; not claimed** |
| Saved root/hash/origin/theme after reload | **Blocked downstream; not claimed** |
| Fresh Documents service over the private durable store | Implemented readback, **not exercised because no revision was saved**; not an API process restart |
| Same-turn source/session retirement UI races | Not independently exercised here; strict negative source/view correlation units are separate evidence |
| Jobs/provider/graph/render/general mutations | Zero jobs and zero forbidden counters |

The browser visibly reports unavailable live observation; this run is not SSE
reliability acceptance. Authored graph presentation is not a physics result.
**No GPU, simulator placement, provider, database, or full F4 renderer claim.**

## Failed-predecessor bytes, HTTP counts and artifacts

Browser/proxy observed **34 actual API HTTP exchanges**: 21 GET 200 and 13 POST
200. POSTs were 12 schema validations and one session creation. One additional
candidate-validation request was deliberately aborted inside Chromium before
proxy dispatch; it is not counted as an API exchange. The independent API
baseline made 10 calls: five GET 200, one GET 401, three POST 200 and one
CSRF-negative POST 403. These baseline calls are separate from browser calls.

Save POST count: **0**. `allowed_authoring_writes: []`, `jobs: []`.
Final counters `network/provider/graph/render/workload/subprocess` are all zero.
The API lifespan closed and its private UDS disappeared. Owned-container
cleanup was verified, and fresh Docker label queries returned no resources.

Actual browser-generated downloads:

- [Raw draft: 444 bytes](.runs/arena-f0-5c915a663225/evidence/authoring-raw-download.yaml),
  SHA-256 `c3232bd3c4e9ea575e691d337954dc684d0ee97b323309e8ea0c5d8688f14d76`.
- [Applied draft: 453 bytes](.runs/arena-f0-5c915a663225/evidence/authoring-final-download.yaml),
  SHA-256 `b45f237852c04003827d0f1815c3f36c0058cfd47846bb6758418b3ad9864918`.

Evidence includes the actual production Vite build, built asset hashes,
[Playwright trace](.runs/arena-f0-5c915a663225/evidence/browser-trace.zip),
[reviewed diff](.runs/arena-f0-5c915a663225/evidence/authoring-reviewed-diff.png),
[desktop dark](.runs/arena-f0-5c915a663225/evidence/authoring-1440-dark.png),
[desktop light](.runs/arena-f0-5c915a663225/evidence/authoring-1440-light.png),
[mobile dark](.runs/arena-f0-5c915a663225/evidence/authoring-390-dark.png),
[mobile light](.runs/arena-f0-5c915a663225/evidence/authoring-390-light.png), and
[failure text](.runs/arena-f0-5c915a663225/evidence/browser-failure.txt).

All **39 artifact hashes and 417 staged source hashes** were read back and
verified. Staged source was unchanged; no live-source changes were recorded
during this final capture. Self-authored hashes establish consistency, not
independent authenticity. Earlier failed captures remain intact.

## Explicit profile and strict contract

The default `readonly` profile and prior v3/v2 F0 proofs retain their contract.
`authoring-v1` requires **both** `--browser --layout v7`, uses the same separate
network-none API/browser containers and private UDS, and permits only a keyed
`POST /api/editor/save` beyond session/validation operations. The API firewall
still denies unkeyed Save and every general job/provider/graph/render mutation.
The final API record enumerates allowed authoring writes separately.
Authoring run envelopes explicitly set `mutations_enabled: true` plus the exact
allowlist `['keyed-editor-save-fresh-private-state']`; this is not a zero-writes
claim. Default read-only envelopes remain `mutations_enabled: false`.

Authoring is an additive `schema_version: 1` record inside the existing v2
browser wire/v3 run envelope, identified by `profile: authoring-v1` across
records. The original baseline YAML, validation and view evidence is preserved
separately. The checker does not accept an authoring profile with missing
journeys, contradictory counters, missing downloads/screenshots, a reused
candidate response, changed view/YAML, a mismatched Save request/receipt,
wrong Library revision, wrong reopened origin/root/hash, or mobile overflow.
Fresh revision view UUIDs may differ after reload while exact source identity,
root bytes/hash and validation stay bound.

Synthetic unit evidence is separate:
[arena-f0-unit-e86cd24aa2](.runs/arena-f0-unit-e86cd24aa2/run-proof.json)
passed **104 Python tests and 8 Node tests**, zero failures/skips, owned cleanup
verified. This includes positive authoring-contract fixtures, 19 negative
correlation/semantic mutations, profile anti-downgrade checks, explicit keyed
firewall boundaries, and candidate-versus-fresh-Apply request correlation.
The previously accepted real API proof `arena-f0-85a1b7ff104b` still passes the
updated strict checker without rewriting its evidence. A fresh default read-only
legacy browser/API run also passed:
[arena-f0-4e3fd13ad19c](.runs/arena-f0-4e3fd13ad19c/run-proof.json), including the
actual production build, original edit/restore browser checks, strict checker
and zero remaining owned resources. This preserves the baseline profile; it
does not resolve the authoring failures above.

## Reproduce after production fixes

From `/workspaces/IsaacLab-Arena`:

```sh
python3 scripts/run-functional-checks.py api --browser --layout v7 --profile authoring-v1 \
  --runtime-image sha256:e20b3cc8258b793aaf1fe47c130f54e677fa9c0a6427991cfc1045b743162da5 \
  --provision-manifest web/arena-workbench/tests/e2e/functional-v7/.runs/arena-f0-provision-d94aed8076e8/provision-manifest.json \
  --frontend-dependency-container 964ddf2e645854708368230ff1770495df6f94c2ecca22b17c7d01ebc611f97d
python3 scripts/run-functional-checks.py security-units --node-units
```

No image pull, package installation, published host port, device passthrough,
live-container restart, or external service call is performed. The browser uses
actual production assets, actual API responses and actual CodeMirror. The one
transport-negative route aborts rather than fulfils a synthetic response.
