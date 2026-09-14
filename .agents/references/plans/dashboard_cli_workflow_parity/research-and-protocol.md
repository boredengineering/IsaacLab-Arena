# Persistence and execution protocol: researched design proposal

Status: proposed design detail for `../dashboard_cli_workflow_parity.md`; not implemented or runtime-verified. This appendix explains the consistency boundaries and implementation decisions. The main plan remains the scope authority. Source numbers belong to the Sources section below, not to earlier research presentations.

## 1. Research findings and consequences

| Primary-source finding | Consequence for this repository |
|---|---|
| Neo4j managed transaction functions can be rerun and must be idempotent.[1] | No model calls, filesystem version allocation, process startup or local journal mutation inside a retriable Neo4j callback. Compute an immutable payload first; callback does only bounded graph writes with stable identifiers. |
| `MERGE` by itself does not guarantee pattern uniqueness under concurrent loads; constraints are needed for uniqueness.[6] | Proposed graph identity constraints and collision handling are prerequisites, not an optimization. Verify supported syntax/constraint types against the deployed Community version; do not adopt new-version or Enterprise-only features implicitly. |
| SQLite WAL does not operate over network filesystems.[3] | Keep the journal on validated local storage shared only by cooperating processes on this host. A mounted path is not automatically local storage. Distributed runners need another coordination design; do not advertise this local protocol as Kubernetes scheduling. |
| The transactional-outbox pattern addresses dual writes, but duplicate delivery still requires idempotent consumers.[5] | Commit local durable intent with local outcome metadata, then deliver to Neo4j and reconcile readback. Do not promise a single atomic transaction across YAML files, SQLite, Neo4j and the model provider. No cloud queue/service dependency is proposed. |
| A successful same-filesystem rename can be atomic, but file synchronization does not itself synchronize its containing directory entry.[7][8] | Stage complete files on the destination filesystem, flush buffered content and synchronize it, atomically publish directory/pointer entries under the writer protocol, then synchronize affected directories. Atomic rename is not a substitute for a multi-file commit manifest. |
| SQLite's backup API produces a database snapshot; WAL is part of persistent database state while in use.[11][3] | Do not back up only a live main database file with a casual copy. Coordinate a database snapshot with pinned artifact manifests and retain necessary immutable files until backup completion. |

These are general guarantees from the cited documentation, not proof that the current implementation provides them. Source redirects may lead to newer Neo4j documentation: implementation must test the actual deployment's capabilities and pin compatible queries. Host storage/controller failures can defeat durability assumptions; document the tested filesystem and storage boundary rather than claim universal crash safety.

## 2. Alternatives considered

- **Wrap CLI main in an HTTP handler:** rejected. It imports simulator-related modules, exposes permissive paths/flags and has duplicate/best-effort side effects. It cannot provide the required bounded worker and credential boundary.
- **Make each interface allocate versions independently with only a directory lock:** insufficient. It does not coordinate job idempotency, publication, crash outcome or evaluation history; a non-cooperating legacy writer bypasses the lock.
- **Add a distributed workflow engine/broker now:** deferred. It adds deployment, authentication and operational dependencies without fixing existing identity/receipt semantics. The contracts should permit a later replacement.
- **Extend the existing local journal plus immutable artifacts and a graph outbox:** selected for the local design. It fits existing durable jobs, typed APIs, owned processes and DCRG integration. It requires an explicit writer cutover and local-storage constraint, not just extra tables.

## 3. Authorities, identities and invariants

Proposed records (not existing schema names):

- `store_id`: fixed identity of a configured research store; path spelling or a container alias is not identity.
- `workflow_id` / immutable request digest: accepted user operation. Existing workspace idempotency key binds to this operation; same key/different request conflicts.
- `attempt_id` and monotonic attempt generation: a particular authorized execution. A receipt from an obsolete attempt cannot change the current attempt's state.
- `candidate_receipt`: bounded output plus exact source/model/catalogue/prior/check provenance. It can exist without a numbered research version.
- `version_reservation`: unique `(store_id, family, version_number)` and unique workflow-to-version mapping. Selected parent revision is explicit, never silently the latest version.
- `artifact_manifest`: immutable file IDs/digests, raw YAML/include hashes, canonicalization scheme and canonical digest. Different canonicalization schemes are recorded separately and mapped; existing DCRG and workbench hashes are not assumed equal.
- `publication_intent`: stable effect ID, target profile revision/database identity, payload digest, graph schema version, authorization scope and local version reference.
- `run_receipt`: unique run ID, exact environment/config/checkpoint/controller identity, requested and actual episode/step/seed counts, artifacts and termination reason. New evaluations append receipts rather than replacing prior evidence.

The local journal is authoritative for accepted commands, reservations and local commit state. Immutable manifests/bytes are authoritative evidence for their content. Neo4j is a separately acknowledged projection/experience store, not proof a local workflow completed. `latest` and human-readable lineage exports are derived conveniences, not the source of version allocation or evaluation selection. DCRG's own run ledger/outbox remains authoritative for DCRG-owned effects; the dashboard stores links, not a competing execution ledger that replays them.

Invariants:

I1. A frozen accepted request never changes through editor edits, configuration rotation or `latest` updates.
I2. No irreversible external work before an authorized, recorded attempt; no stale receipt can complete another attempt.
I3. No automatic replay of ambiguous model calls or simulation runs.
I4. A committed version is immutable and bound to exactly one reservation/workflow; reserved numbers are never reused after uncertain failure.
I5. Publication payload and target are immutable; retries cannot allocate another version or invoke the agent again.
I6. “Published” requires exact graph readback, not HTTP/worker/process success or node counts alone.
I7. A cleanup-unknown worker retains its resource reservation; another simulator is not admitted merely because the parent exited.
I8. Cancelled/expired authorization blocks new effects, but cannot claim to retract an already accepted external effect.
I9. A measured result is attached only to the exact scene and policy/controller identity actually used; missing evidence stays unknown.
I10. Feature rollback disables new submission without deleting accepted work, immutable artifacts or pending intents.

## 4. Local version commit protocol

All CLI and dashboard writers targeting a new managed store use the same registry and protocol version. Do not change existing generation outputs in place during migration. Introduce an operator-approved managed root on persistent local storage; import historical artifacts read-only with origin hashes. Preserve access to legacy directories. Updated CLI exposes the selected store/output profile explicitly; any change from historical `--out_dir` behavior is documented and characterized.

A protocol file cannot prevent an arbitrary old process with write permissions from changing files. Therefore strict guarantees apply only after a controlled writer cutover: drain managed work, identify legacy writers, place the managed root outside their legacy default outputs, and require compatible writer/store identity checks. Existing live graph destinations additionally require a compatible namespace/identity strategy. Do not claim safety against arbitrary privileged local edits; detect content mismatch and quarantine it.

1. Accept/freeze request in a short journal transaction. Never hold the write transaction while calling a provider or simulator.
2. Run authorized generation; persist its candidate receipt before marking generation complete. Missing receipt after an uncertain provider call is indeterminate, not permission to regenerate.
3. For requested version persistence, reserve family/version and parent in one short transaction with uniqueness constraints. Retried workflow finds the same reservation. Failed reservations can leave gaps; do not reuse them.
4. Write staged artifacts and manifest under a reservation-owned staging directory on the destination filesystem. Enforce safe identifiers, no-follow/root-containment checks and size limits; freeze all includes/configs. Complete and synchronize files before promotion.
5. Promote to a previously unoccupied final version directory with no-clobber behavior. If the destination already exists, verify its reservation ID, original candidate receipt, attempt generation and complete manifest digest as one binding; matching content reconciles, mismatching content blocks. Post-promotion adoption must never synthesize a missing generation receipt from YAML alone. Never overwrite an existing version to make a retry pass. Synchronize the directory metadata.
6. In one local journal transaction, mark the exact reservation/artifact manifest committed and create its requested publication intent, plus the corresponding event. A graph write cannot begin before this commit.
7. Regenerate human-readable lineage and update `latest` from the highest locally committed version under the store writer protocol; compare the expected predecessor/generation so a slow earlier writer cannot move it backwards. Pointer/export repair never changes immutable version data.

Crash handling: before promotion, keep/quarantine staging and its reservation; after promotion but before journal commit, verify bytes and adopt the exact prepared version without rerunning generation; after journal commit, recover pending publication and derived views. Missing/mismatched committed artifacts block publication/evaluation and require operator repair, not synthetic regeneration. Retention cannot remove staging, committed artifacts or receipts referenced by active/unknown attempts, publication intents, run evidence or backups. Garbage collection is a separate bounded, dry-run/reviewable maintenance operation.

## 5. Publication protocol and graph compatibility

1. Resolve the already-authorized destination profile revision and source payload. Model credentials and graph credentials are separate; neither belongs in journal payloads or argv.
2. Atomically claim a pending intent with an attempt/fencing generation and bounded lease. Recheck cancellation and authorization immediately before releasing the private connection configuration and issuing a new transaction.
3. Within a bounded Neo4j transaction, enforce the stable effect/revision identity and expected digest. Existing matching content is an idempotent success; same identity/different digest is a conflict, never `SET`-overwrite repair. Precompute timestamps/IDs outside retry callbacks.
4. For payloads too large for the agreed transaction bound, do not fall back to visible partial graph writes. Either reject with an actionable bound or use explicitly designed staging plus a completion marker that every reader honors; the initial implementation prefers bounded single-transaction publication.
5. Read back the exact identity/schema version/digest and canonical projected content (not merely a stored digest property copied from the request). Verify node/relationship identities and endpoints, protected by the same visibility/consistency contract. In clustered routing, use causal/session consistency so a stale read does not falsely report missing data.
6. Record the verified receipt in a local transaction with an event. If DB commit happened but acknowledgement/readback was lost, mark outcome unknown and reconcile the same effect ID on the same destination before any replay. No model or version-allocation work occurs in this reconciliation.

A negative readback is not proof of no effect while an earlier released transaction can still commit. Retain outcome unknown until its termination is established or a tested database-side serialization/fencing protocol establishes a definitive outcome. Do not issue another physical write merely because a first read returned no rows. Tests must cover release-with-no-confirmed-send, late commit after a negative read and bounded readback timeout.

New revision identity must preserve DCRG full canonical digests and detect shortened-name collisions. Legacy `EnvironmentGraph` names, asset IDs and retrieval filters are not rewritten speculatively. P2 requires schema fixtures covering DCRG-compatible canonical revisions, unsupported-DCRG task graphs, existing mutable-name projections and retrieval membership. Every revision-scoped node/edge must be scoped consistently so old and new scenes cannot merge through shared object IDs. A compatibility view cannot double-count both the old mutable graph and the new revision as independent evidence. The accepted schema and retriever queries are a P2 design/test gate before enabling publication, not an assumed implementation detail.

Proposed intent states: `not_requested`, `pending`, `claimed`, `outcome_unknown`, `verified`, `blocked_authorization`, `blocked_conflict`, `failed_retryable`, `cancelled_before_send`. A cancellation after transaction release can end with verified published content or unknown outcome; show “execution cancelled; publication already committed/unknown” rather than delete the graph or claim it was undone. Generation, local persistence, graph publication and evaluation statuses remain separate.

## 6. Authorization, attempts and recovery

### 6.1 Separate grants and queued authorization

Model execution, retrieval-read, publication-write and exact-effect reconciliation-read use separate grants. Every grant binds an immutable profile revision, operator/principal scope (declared versus externally verified distinguished), credential generation, expiry, workflow/effect and attempt scope. These are proposed records, not existing API fields. Only nonsecret metadata enters the journal. Private bytes are resolved at authorized dispatch and checked again after any worker-spawn await; if the original generation is unavailable, block rather than substitute current environment credentials.

Before first irreversible release, unavailable/expired grants put work into `blocked_authorization` with no external attempt. That state still counts against bounded retained/pending-work quotas; it does not poll for automatic credential replacement. Explicit renewal creates a linked authorization record and a new pre-release attempt for the same frozen operation/profile/principal scope, never mutates its original request or credential reference. Model, endpoint, scene or principal-scope changes require a new reviewed operation. Ambiguous post-release work is not eligible for this renewal-as-retry path. Once a bounded model attempt was validly released, its previously authorized call budget may finish as already disclosed; this does not authorize later publication or another model attempt.

### 6.2 Every physical write attempt is authorized

The initial publisher uses explicit Neo4j transactions with no automatic write-transaction retry API. Application-level retry first reconciles the stable effect, then separately authorizes and records a new physical attempt. Do not use `execute_write`/retrying `execute_query` for publication unless every callback invocation acquires the same guarded authorization; the selected initial design avoids that extra ambiguity. Retry-safe payloads are still required for commit-ack loss.

Send/revocation ordering is defined at the local coordinator: the compare-and-set release record checks grant generation, deadline, cancellation epoch and attempt identity atomically. Revocation committed before release prevents sending. Once release commits, one bounded transaction may already reach Neo4j; later cancellation triggers best-effort cleanup but cannot promise rollback of a committed effect. No subsequent physical transaction is permitted under that release. Record release-with-no-confirmed-send as outcome unknown until reconciled; do not infer no effect from process exit.

The write grant does not govern acknowledgement of an already released effect. A separate bounded read grant authorizes only exact-effect/destination reconciliation after write revocation or expiry. If that read grant/configuration is unavailable, retain `outcome_unknown` and offer explicit reconciliation-only authorization. A missing readback never restores write permission. No duplicate inference, version allocation or destination change occurs during readback.

- Add compare-and-set transition guards and attempt IDs to the existing journal contract; its current generic transition method alone is insufficient. Claim/authorize/start/complete operations check expected prior state and attempt generation in the same transaction as their events.
- A live temporary model reference is checked at original authorization and again after worker startup, as today. An already-authorized bounded model operation may complete its authorized calls; expiry does not grant permission for a new attempt or a later graph publication.
- Disable hidden SDK/transport retries for potentially executed model calls unless the selected provider has a tested idempotency contract bound to that exact call. Test SDK behavior as well as coordinator redispatch; an ambiguous completion remains unknown even when a generic client library considers the error retryable. A new authorized repair call after a known response is distinct from replaying an uncertain request.
- Publication gets explicit bounded authorization tied to destination/payload/scope, not an implicit infinite entitlement because a model job once existed. Defaults: cancellation/revocation/authorization expiry suppress new publication attempts; an operator may renew publication-only authorization to the same frozen effect/destination. Different destination/principal scope is a new reviewed intent, not retry.
- On restart, pause dispatch, inspect owned worker identities and durable receipts, and reconcile outcomes. A verified completed receipt can be adopted without redispatch. No receipt means indeterminate. If an operator deliberately repeats an ambiguous provider/simulation operation, create a new linked operation with a duplicate-work warning, never rewrite the old outcome as failed to unlock retry.
- Temporary credential loss on restart is not repaired by secretly using a server-environment key. Server-model and graph credential rotation follow the same immutable generation/explicit renewal rules as temporary references; unavailable original material blocks dispatch. An operator-authorized same-scope renewal is recorded separately, never silently applied to queued requests.
- Queue resumption lists exact job IDs and prerequisites. Selection is server-enforced; if only whole-queue resume is supported, the UI must show and confirm the whole affected queue. Retained `cancel_requested` or unknown attempts never become ordinary queued work.

## 7. Runtime resource ownership and dependency order

Before simulation/evaluation features, provide an execution admission layer with one authoritative owner/lease per configured runtime resource, bounded wait deadlines and cleanup acknowledgement. Retire the warm snapshot worker, verify its owned descendants and lease release, then start evaluation; recreate snapshots lazily. A timeout during handoff leaves an explicit blocked resource, not competing workers. Do not stop shared external GR00T/OpenPI servers.

The next worker must atomically acquire and hold the same cross-clone resource lease before initialization. A release probe followed by an unleased launch is not a handoff. Test cancellation while waiting/acquiring, child spawn racing parent cancellation, and grandchildren surviving an exited parent.

### 7.1 Remote policy identity after preflight

Bind preflight to immutable endpoint profile revision and the observed server instance/checkpoint/config identity. Revalidate immediately before rollout and on every reconnect. A mismatch stops new policy actions, preserves partial evidence and requires a newly reviewed operation; a same URL is not proof of the same weights. Execute local models from pinned immutable weight artifacts rather than mutable `latest` aliases.

Where a server cannot attest or pin its checkpoint/session for the run, require explicit `unverified_identity` operator approval. Store declared checkpoint separately from observed transport metadata; prohibit checkpoint-verified attribution and matched-checkpoint acceptance claims. A one-time handshake cannot prove weights stayed fixed through the run. Verified mode requires a stable server session/immutable managed artifact contract or per-response identity that detects changes before accepting actions. Record the verification method and its limitations. This rule also applies to controller-assisted comparisons: a policy class/config name cannot satisfy weight identity.

### 7.2 Schema compatibility and rollback ownership

Before new writes, record journal schema, managed-store protocol, graph schema and receipt canonicalization versions plus supported reader/writer ranges. Unknown/newer incompatible versions cause mutation refusal—no automatic downgrade. Migration requires draining writers, a verified backup/artifact manifest, exclusive migration ownership and recovery tests before enabling new submissions. Read-only historical import is distinct from migration.

Feature rollback first disables new submissions. A retained compatible recovery supervisor owns cancellation, cleanup, receipt adoption and outbox reconciliation for accepted operations; older binaries cannot claim those attempts or mutate their stores. If no compatible recovery process is available, keep dispatch paused and retain unknown outcomes/resources until an operator restores a compatible version. Backups and schema rollback do not erase already committed Neo4j effects; reconcile them against immutable intents rather than restoring a local backup and pretending they never occurred.

Dependency gates: attempt/CAS transitions, frozen profiles/grants and candidate-receipt recovery before P1 dispatch; versioned compatibility/backup and writer-cutover before P2 mutation; GPU admission/handoff before P3; policy identity and run evidence before P4; owned descendants plus DCRG authority integration before P5. P6 is display/operator usability completion, not a place to postpone these foundational safety mechanisms.

Nested experiments/DCRG have a parent workflow and individually recorded children, cumulative budget reservations and cancellation propagation. Parent cancellation prevents admission of new children; running children finish cleanup before their lease is released. Partial evidence is retained and counted; a controller's own durable resume and publication ownership remain intact. Failed publication of completed evaluation does not rerun that evaluation.

Local Kit launch is a desktop session, not a browser stream. WebRTC requires separate routing/authentication/display review. Report HTML is untrusted output and must not inherit the dashboard origin's cookies/credential privileges. Readiness polling does not perform inference, checkpoint downloads, initialization with hidden provider calls, or service startup.

## 8. Verification limits and approvals

The protocol is a design to implement and test, not an assertion that crash tests already passed. Required implementation tests include fault injection at every numbered persistence/publication boundary, concurrent CLI/HTTP writers, stale attempts, revoked grants, commit-ack loss, delayed graph reads, cleanup-unknown processes, corrupted manifests, disk-full/fsync failure and incompatible schema rollback.

Store roots, schema changes, supported Neo4j edition/version, live model/DB/GPU budgets, backup/retention limits and infrastructure changes need explicit approval. No claim of exactly-once model inference, universal filesystem crash durability, distributed scheduling, end-to-end physics correctness, or acceptance of every arbitrary CLI import/argument is made.

## Sources

[1] https://neo4j.com/docs/python-manual/current/transactions
[3] https://www.sqlite.org/wal.html
[5] https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html
[6] https://neo4j.com/docs/cypher-manual/5/clauses/merge
[7] https://docs.python.org/3.12/library/os.html
[8] https://man7.org/linux/man-pages/man2/fsync.2.html
[11] https://sqlite.org/backup.html
