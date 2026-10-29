# Foreground workflow: isolated acceptance runbook

## Status and limits

The shared application now executes initial generation → schema validation → observation/assessment → permitted repair → fresh observation/assessment → acceptance or an explained stop. New workflow decisions, lineage and budgets are Neo4j-owned; immutable files retain model, candidate, observation and cleanup evidence.

**The guarded isolated workflow milestone is complete; this is not a production deployment.** The supported `workflow-cli` launcher initializes the explicitly admitted environment and runs the public module in separate interpreters against the same disposable database. There is no general configured-provider factory outside that environment; an unbootstrapped ordinary-shell invocation remains not-ready. Shared observation-only bootstrap is wired; installed-host startup remains unavailable. The final bounded recheck closes all five findings for this isolated scope, and the final parent source-matching rerun passed with verified cleanup.

Native simulation, live inference, shared-service changes and research-database operations remain disabled. Synthetic capture cannot establish physical support, stability, policy success or causality. Synthetic HTTP responses exercise the real agent/SDK path; they are not model-quality evidence.

## Reproduce the joined CLI/application proof

From the repository root, with the already admitted Docker images available:

```sh
python3 scripts/run-workflow-neo4j-checks.py workflow-cli
```

Do not pull/install an image or redirect this command at an existing database to repair missing prerequisites. The runner owns a disposable Neo4j instance and an internal isolated network, publishes no ports, captures source bytes, enforces the exact child/SDK profile, and verifies cleanup. A missing prerequisite is a blocker, not permission to weaken the guards.

The runner prints an output directory under:

```text
web/arena-workbench/tests/e2e/functional-v7/.runs/arena-neo4j-<unique-id>/
```

It launches fresh interpreters executing the actual public CLI module and default factory, without injecting an application factory. The application, not the test, selects the next scene action. Initial generation uses the actual proposal-only `generate_spec`; model HTTP replies and capture inputs are controlled fixtures. The suite also launches separate cancellation/status/resume clients. Allow the full 780-second CLI collector budget for the expanded interruption cohort; ordinary modes and worker deadlines are unchanged. When using a tool with a shorter transport timeout, launch the command as a tracked background task; do not increase worker deadlines. The complementary `workflow-scene` mode tests the in-process application/scene composition.

Inspect these retained files:

- `run-proof.json`: overall result, source hashes, isolation and cleanup.
- `evidence/pytest.xml`: test names, failures/errors/skips.
- `evidence/client-proof.json`: denied-effect counters and client disposition.
- `evidence/workflow-cli.json` and `workflow-cli-transcript.json`: fresh commands, admission/output frames, cancellation/continuation assertions and SDK references.
- `evidence/workflow-cli-*.json`: independent CLI-process preimport/guard/ownership witnesses.
- In `workflow-scene` runs, `workflow-application.json` and `workflow-scene-ports.json` retain the corresponding application/scene traces.
- `evidence/generation-child-*-sdk.json`: synthetic transport counts, not provider billing.

The disposable database is removed after the run. Historical IDs in those receipts cannot be queried against a new runner instance. Evidence remains on disk; this is not a persistent service installation.

## CLI wire implemented

The four-command public module is `isaaclab_arena_examples.agentic_environment_generation.foreground_workflow_cli`, invoked by the guarded launcher. Core `isaaclab_arena.agentic_environment_generation.workflow.cli` remains inspect-only and does not import the examples adapter.

- Core `inspect-contract PATH`: parses declared intent without readiness checks or execution.
- `run --config PROFILE --principal ID --operation-id ID CONTRACT`: delegates one requested workflow to the shared application.
- `status --config PROFILE --principal ID RUN_ID`: reads authoritative retained state and available actions.
- `cancel --config PROFILE --principal ID RUN_ID`: delivers an authenticated scoped local stop to the owner before client DB access, then separately requests durable cancellation. Inspect `local_stop` and `durable_cancellation`; a delivery ACK is not physical cleanup evidence for another process.
- `resume --config PROFILE --principal ID [--renew-authorization] RUN_ID`: replays settled state or continues supported exact known-unreleased work. Renewal is explicit; it does not change frozen intent, original deadline or reserved charges. Uncertain released effects are never automatically redispatched.

These commands are wired to the fixed isolated factory, not arbitrary Python plugins. `status`, completed replay and capability reads do not issue model grants, bootstrap services or construct models. Output is JSONL: a flushed `{schema_version:1,event:"admitted",result:...}` handle precedes expensive work, followed by the final `{schema_version:1,result:...}`. Public results include criterion verdicts, selected/historical evidence identities, conservative reservations/remaining allowances, unknown actual consumption, and publication/experiment/cleanup/recovery dispositions. Never interpret `reserved` as actual provider billing.

Profile v1 has exactly `schema_version`, `composition`, `database`, `deployment_id`, `workspace_id`, `artifact_root`, and `lease_root`. Composition is `isolated-synthetic-v1`. The database object contains `uri`, `database`, and `username`, never a password. Paths are explicit absolute paths, and the profile is an owner-private singly-linked regular file. The harness supplies the exact isolated endpoint and initializes the disposable operational scope and artifact area before the default factory opens them.

Optional `--credentials-fd N` parses bounded JSON from a same-UID private pipe, with a finite deadline. Never put credentials on argv, in shell history or in the public profile. A pipe is not a sandbox against the same OS user or a privileged host. The current isolated default factory accepts no credentials and no startup permission; real credential entry is not exercised or required by this runbook.

Outcome exits: 0 accepted, 2 invalid input, 3 blocked/not-ready/unknown, 4 denied, 5 failure, 6 stopped, 7 cancelled. Required frozen-model mismatch has the typed static error `model_profile_not_ready` and exit 3, verified for both required model roles before admission or SDK activity. Unexpected `ValueError` remains failure, not blanket readiness success/refusal. `--allow-startup` never authorizes broad Docker/API startup; no installed scoped helper is configured.

## Ownership order and recovery

1. Admit the complete request, supported producer/rubric and required dependency/role closure before the first model construction/ping.
2. Capture explicit private role authority; retain the initial prior and original deadlines.
3. Generate under the existing coordinator, verify/promote generation artifacts, adopt, acknowledge actual cleanup, retire the generation owner and read back before unlocking.
4. Acquire/register the fresh physical scene owner before `start_scene` reserves scene work.
5. Across observe/repair/observe, keep the same physical flock. Advance only after supervisor-authenticated physical cleanup plus authoritative produced-stage readback.
6. Retire terminal scene ownership only after exact settlement/readback. Database-deserialized cleanup is not the supervisor's physical capability.

A store outage does not authorize another effect. Local stop and retained physical cleanup remain available to the actual owner, while durable cancellation may remain unknown. The integrated outage proof injects `StoreUnavailable` into the cancel client; it is not a Neo4j-server shutdown or simultaneous outage of every participant. The owner has a bounded 20-second reconciliation grace. Prepared/released uncertainty and stale endpoints fail closed. Real pre-prepare dispatch interruptions now cover same-root recovery before reservation and fresh-process recovery after owner registration but before claim, preserving original admission and any existing reservation. No invented cleanup or unrestricted dirty-owner takeover is permitted.

## Parent-verified evidence at this checkpoint

| Cohort | Directory suffix | Result | Scope |
| --- | --- | --- | --- |
| Final parent CLI composite | `arena-neo4j-6fe820f218de4774a8cb46c049125986` | 1 composite case; 31 CLI processes / 28 SDK workers | Real Neo4j/processes; synthetic HTTP/capture; all correction assertions and final Python hashes match |
| Parent scene rerun | `arena-neo4j-3c602a82680e48cb95166879c7e293b9` | 11 passed | Final scene harness/application composition and scoped recovery |
| Core workflow suites | `arena-f0-backend-b97e6c7603b8` | 471 passed | Contracts, service, evidence, guards and CLI units; not native execution |
| Operational store | `arena-neo4j-a6eb8b67a3ae4c9999d8e3e2d3ef4698` | 139 passed | Disposable real Neo4j lifecycle/races; synthetic physical ports in metadata tests |
| Scene worker/process | `arena-f0-backend-bc34e1b9262c` | 39 passed | Actual child ownership and SDK serialization; synthetic store/capture/HTTP |
| Initial generation worker | `arena-f0-backend-54e4904d7c0b` | 4 passed | Actual generation, retained prior, schema/adoption and zero calls for unavailable required prior |

Each listed proof had zero failures/errors/skips and verified cleanup at its captured revision. Do not add overlapping counts or relabel older source as later verification. One parent foreground rerun was interrupted by the tool's 420-second transport limit (`arena-neo4j-6fbc9926a07c4a3b99a4e7504eb2a8ec`); its SIGTERM and verified cleanup are retained separately, not counted as feature acceptance.

The six dependency-negative cases check runtime, operational Neo4j, generation model, assessment model, capture and GPU requirements in the synthetic dependency profile, with zero generation-factory calls and no SDK children. They are not live health or GPU availability measurements.

## Final verification and deferred gates

- All original review findings and the final parent snapshot gate are closed. No additional implementation or review is pending within the guarded isolated milestone.
- Preserve the distinction between the supported guarded isolated launcher and a production operator deployment.
- The default isolated prior remains an explicit unavailable fallback. Separate component evidence covers nonempty retained-prior consumption, not live research retrieval.
- Retain native/live/deployment status as not performed. Dashboard integration, policy/VLM-assisted DCRG and legacy Journal migration remain later work.
