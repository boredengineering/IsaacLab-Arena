import React, { useEffect, useId, useState } from 'react';

type JobStatus = 'queued' | 'running' | 'blocked_authorization' | 'cancel_requested' | 'indeterminate' | 'succeeded' | 'failed' | 'cancelled';
type ExampleJob = {
  id: string;
  kind: string;
  status: JobStatus;
  stage: string;
  inputs: Record<string, string | number>;
  result?: Record<string, string | boolean>;
  error?: string;
};
// Static, public teaching fixtures. These are not observed jobs or research evidence.
const jobs: ExampleJob[] = [
  { id: 'example-queued', kind: 'diagnostic', status: 'queued', stage: 'waiting_for_explicit_resume', inputs: { steps: 3, delay_seconds: 1 } },
  { id: 'example-running', kind: 'diagnostic', status: 'running', stage: 'bounded_steps', inputs: { steps: 4, delay_seconds: 0.5 } },
  { id: 'example-blocked', kind: 'generate', status: 'blocked_authorization', stage: 'authorization_required', inputs: { source: 'example-source-v1', operation: 'refine' }, error: 'Example authorization unavailable; generation has not resumed.' },
  { id: 'example-cleanup-pending', kind: 'diagnostic', status: 'cancel_requested', stage: 'worker_cleanup_pending', inputs: { steps: 3, delay_seconds: 1 } },
  { id: 'example-indeterminate', kind: 'diagnostic', status: 'indeterminate', stage: 'outcome_unverified', inputs: { steps: 3, delay_seconds: 1 } },
  { id: 'example-succeeded', kind: 'diagnostic', status: 'succeeded', stage: 'complete', inputs: { steps: 1, delay_seconds: 0.1 }, result: { fixtureOnly: true, description: 'Illustrative diagnostic completion shape; not an executed test or robotics result.' } },
  { id: 'example-failed', kind: 'diagnostic', status: 'failed', stage: 'diagnostic_error', inputs: { steps: 3, delay_seconds: 1 }, error: 'Example diagnostic failure; real logs and results are unavailable.' },
  { id: 'example-cancelled', kind: 'diagnostic', status: 'cancelled', stage: 'cleanup_acknowledged_example', inputs: { steps: 3, delay_seconds: 1 } },
];
const active = (job: ExampleJob) => ['queued', 'running', 'blocked_authorization', 'cancel_requested'].includes(job.status);
const json = (value: unknown) => JSON.stringify(value, null, 2);
const statusLabel = (job: ExampleJob) => job.status === 'cancel_requested' ? 'cleanup-pending (cancel_requested)' : job.status === 'blocked_authorization' ? 'blocked (blocked_authorization)' : job.status;
// Component-safe projection of the journal fixtures, never a second feed.
// Attention overlaps active: blockers, cleanup, unverified outcomes and failures.
export const exampleJobSummaries = Object.freeze(jobs.map(job => Object.freeze({
  id: job.id,
  kind: job.kind,
  status: job.status,
  statusLabel: statusLabel(job),
  stage: job.stage,
  isActive: active(job),
  needsAttention: ['blocked_authorization', 'cancel_requested', 'indeterminate', 'failed'].includes(job.status),
})));
const renewable = (job: ExampleJob) => job.kind === 'generate' && job.status === 'blocked_authorization' && ['new', 'refine'].includes(String(job.inputs.operation));
type JobActionReview = { exampleOnly: true; action: 'cancel' | 'authorization-renewal'; target: ExampleJob; authorization: string };

function JobActions({ job, onFreeze, hasFrozen }: { job: ExampleJob; onFreeze: (review: JobActionReview) => void; hasFrozen: boolean }) {
  const [authorization, setAuthorization] = useState('unknown');
  const [pending, setPending] = useState<JobActionReview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const canCancel = ['queued', 'running'].includes(job.status) || renewable(job);
  if (!canCancel) return null;
  function review(action: JobActionReview['action']) {
    setConfirmed(false);
    setPending({ exampleOnly: true, action, target: { ...job, inputs: { ...job.inputs } }, authorization: action === 'authorization-renewal' ? 'example-public-authorization-available' : 'not-applicable' });
  }
  return <section aria-label="Example job actions">
    <p className="preview-muted">Eligibility reflects this static fixture only, never live permission. Reviews cannot cancel or authorize work.</p>
    {renewable(job) && <label className="preview-field">Authorization example<select aria-label="Authorization example" value={authorization} onChange={event => { setAuthorization(event.target.value); setPending(null); setConfirmed(false); }}><option value="unknown">Unknown / disconnected — no authority</option><option value="available">Available public authorization example (no secret)</option></select></label>}
    <div className="preview-actions"><button type="button" disabled={hasFrozen} onClick={() => review('cancel')}>Review cancellation</button>{renewable(job) && <button type="button" disabled={hasFrozen || authorization !== 'available'} onClick={() => review('authorization-renewal')}>Review authorization renewal</button>}</div>
    {pending && <section className="preview-panel" aria-label="Pending exact job action"><h4>Confirm frozen example target</h4><pre>{json(pending)}</pre><label className="preview-field"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />Confirm this exact example job action; nothing will be sent</label><div className="preview-actions"><button type="button" disabled={!confirmed || hasFrozen} onClick={() => { if (confirmed) onFreeze(pending); setPending(null); setConfirmed(false); }}>Freeze job action review</button><button type="button" onClick={() => { setPending(null); setConfirmed(false); }}>Dismiss pending job action</button></div></section>}
  </section>;
}

type DiagnosticRequest = { exampleOnly: true; kind: 'diagnostic'; idempotency_key: string; inputs: { steps: number; delay_seconds: number } };
type QueueReview = { exampleOnly: true; action: 'resume-queue'; cursor: string; targets: { id: string; kind: string; status: JobStatus }[] };

function QueueResume({ enabled, onFreeze }: { enabled: boolean; onFreeze: (review: QueueReview) => void }) {
  const [pending, setPending] = useState<QueueReview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  return <section className="preview-panel" aria-label="Queue resume example"><h3>Explicit queue resume review</h3>
    <p>Resume can affect the entire pending queue, not only diagnostic work; generation and GPU jobs require their own authorization. Review every queued identity before any real resume. This preview sends nothing.</p>
    <button type="button" disabled={!enabled} onClick={() => { setConfirmed(false); setPending({ exampleOnly: true, action: 'resume-queue', cursor: 'example-cursor-008', targets: jobs.filter(job => job.status === 'queued').map(({ id, kind, status }) => ({ id, kind, status })) }); }}>Review queue resume</button>
    {pending && <><pre aria-label="Pending queue resume review">{json(pending)}</pre><label className="preview-field"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />Confirm review of the entire example queue; do not resume it</label><div className="preview-actions"><button type="button" disabled={!enabled || !confirmed} onClick={() => { if (enabled && confirmed) onFreeze(pending); setPending(null); setConfirmed(false); }}>Freeze queue resume review</button><button type="button" onClick={() => { setPending(null); setConfirmed(false); }}>Dismiss queue resume review</button></div></>}
  </section>;
}

function DeveloperDiagnostics({ snapshot }: { snapshot: string }) {
  const [capability, setCapability] = useState('unknown');
  const [consent, setConsent] = useState(false);
  const [steps, setSteps] = useState('3');
  const [delay, setDelay] = useState('1');
  const [retainedState, setRetainedState] = useState('none');
  const [retained, setRetained] = useState<DiagnosticRequest | null>(null);
  const [frozen, setFrozen] = useState<DiagnosticRequest | null>(null);
  const [retryReview, setRetryReview] = useState<DiagnosticRequest | null>(null);
  const [discardConsent, setDiscardConsent] = useState(false);
  const [nextRequest, setNextRequest] = useState(1);
  const [queueReview, setQueueReview] = useState<QueueReview | null>(null);
  const enabled = capability === 'available' && consent;
  const bounded = /^\d+$/.test(steps) && Number.isInteger(Number(steps)) && Number(steps) >= 1 && Number(steps) <= 10 && delay.trim() !== '' && Number.isFinite(Number(delay)) && Number(delay) >= 0.1 && Number(delay) <= 5;
  const canFresh = enabled && bounded && retainedState === 'none' && !frozen && !retryReview;
  const canRetry = enabled && retainedState === 'unresolved' && !!retained;
  function reviewFresh() {
    if (!canFresh) return;
    const request: DiagnosticRequest = { exampleOnly: true, kind: 'diagnostic', idempotency_key: `example-diagnostic-request-${nextRequest}`, inputs: { steps: Number(steps), delay_seconds: Number(delay) } };
    setNextRequest(nextRequest + 1);
    setFrozen(request);
    setRetained(request);
    setRetainedState('unresolved');
    setDiscardConsent(false);
  }
  function loadRetention(value: string) {
    if (retainedState !== 'none' || frozen || retryReview) return;
    setRetainedState(value);
    setDiscardConsent(false);
    setRetained(value === 'unresolved' ? { exampleOnly: true, kind: 'diagnostic', idempotency_key: 'example-retained-diagnostic-001', inputs: { steps: 3, delay_seconds: 1 } } : null);
  }
  return <section aria-label="Developer diagnostics form"><h3>Integration diagnostic — bounded, test-only example</h3>
    <p>Operational lifecycle review is separate from Runs & evidence. No custom-input logs, completion result or robotics metrics are generated. Nothing is submitted, persisted or scheduled; all retained state exists only in this mounted preview.</p>
    <label className="preview-field">Diagnostic capability example<select aria-label="Diagnostic capability example" value={capability} onChange={event => { setCapability(event.target.value); setConsent(false); setDiscardConsent(false); }}><option value="unknown">Unknown / disconnected — no authority</option><option value="disabled">Disabled example capability</option><option value="available">Enabled capability + session example — review only</option></select></label>
    <label className="preview-field"><input type="checkbox" checked={consent} disabled={capability !== 'available'} onChange={event => setConsent(event.target.checked)} />Consent to local diagnostic review only</label>
    <div className="preview-grid"><label className="preview-field">Steps<input aria-label="Steps" type="number" min="1" max="10" step="1" value={retained?.inputs.steps ?? steps} disabled={!enabled || retainedState !== 'none' || !!frozen || !!retryReview} onChange={event => setSteps(event.target.value)} /></label><label className="preview-field">Delay per step (s)<input aria-label="Delay per step (s)" type="number" min="0.1" max="5" step="0.1" value={retained?.inputs.delay_seconds ?? delay} disabled={!enabled || retainedState !== 'none' || !!frozen || !!retryReview} onChange={event => setDelay(event.target.value)} /></label></div>
    {!bounded && <p role="alert">Steps must be whole numbers from 1–10; delay must be finite and between 0.1–5 seconds.</p>}
    <div className="preview-actions"><button type="button" className="primary" disabled={!canFresh} onClick={reviewFresh}>Review diagnostic request</button><button type="button" disabled={!canRetry} onClick={() => { if (canRetry) setRetryReview(retained); }}>Review retained retry</button></div>
    <section className="preview-panel" aria-label="Retained request handling"><h4>Retained request example</h4>
      <label className="preview-field">Retained request example state<select aria-label="Retained request example state" value={retainedState} disabled={retainedState !== 'none' || !!frozen || !!retryReview} onChange={event => loadRetention(event.target.value)}><option value="none">None — no retained example</option><option value="unresolved">Unresolved same-ID request example</option><option value="invalid">Invalid retained record example</option><option value="unavailable">Retention unavailable example</option></select></label>
      <p aria-label="Retained state summary">Retained example state: {retainedState}. {retainedState === 'unresolved' ? 'In a live system, acceptance could be unknown: retry must reuse the same ID and frozen inputs. Here nothing was sent or accepted.' : retainedState === 'invalid' ? 'Malformed retention is unresolved, not absent. No replacement ID or retry can be inferred.' : retainedState === 'unavailable' ? 'Retention cannot be read or written in this example. Fresh and retry reviews are blocked; do not infer an absent request.' : 'No pending example request. No server disposition is implied.'}</p>
      {retained && <pre aria-label="Retained diagnostic request">{json(retained)}</pre>}
      <label className="preview-field"><input type="checkbox" checked={discardConsent} disabled={retainedState === 'none'} onChange={event => setDiscardConsent(event.target.checked)} />Confirm local discard; this does not cancel or resolve a server request</label>
      <button type="button" disabled={!discardConsent || retainedState === 'none'} onClick={() => { if (!discardConsent) return; setRetained(null); setRetainedState('none'); setDiscardConsent(false); }}>Discard retained example state</button>
      <p className="preview-muted">Discard resets only this teaching scenario, including simulated unavailable retention. It does not repair storage, cancel a job, or establish whether a real request was accepted. Frozen reviews remain separately labelled until explicitly closed.</p>
    </section>
    {(frozen || retryReview) && <section className="preview-panel" aria-label="Frozen diagnostic reviews"><h3>Frozen local reviews — not sent</h3>{frozen && <><h4>Original diagnostic request</h4><pre aria-label="Frozen diagnostic request">{json(frozen)}</pre></>}{retryReview && <><h4>Same retained-ID retry review</h4><pre aria-label="Frozen retry review">{json(retryReview)}</pre></>}<p>These are retained review records, not current job outcomes. Changing capability or discarding retained state cannot retarget these inputs.</p><button type="button" onClick={() => { setFrozen(null); setRetryReview(null); }}>Close frozen diagnostic reviews</button></section>}
    <QueueResume key={`${snapshot}-${enabled}-${!!queueReview}`} enabled={enabled && snapshot === 'available' && !queueReview} onFreeze={setQueueReview} />
    {queueReview && <section className="preview-panel" aria-label="Retained queue resume review"><h3>Frozen queue resume review — not sent</h3><p>Historical example cursor and queue targets; not a refreshed snapshot or acknowledgment. No queue was resumed.</p><pre aria-label="Frozen queue resume review">{json(queueReview)}</pre><button type="button" onClick={() => setQueueReview(null)}>Close frozen queue resume review</button></section>}
  </section>;
}

export function JobsDiagnosticsPreview({ requestedJob }: { requestedJob?: { id: string; sequence: number } } = {}) {
  const panelId = useId();
  const [tab, setTab] = useState('journal');
  const [filter, setFilter] = useState('all');
  const [snapshot, setSnapshot] = useState('available');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [frozenAction, setFrozenAction] = useState<JobActionReview | null>(null);
  useEffect(() => {
    if (!requestedJob) return;
    setSelectedId(requestedJob.id);
    setTab('journal');
    setFilter('all');
  }, [requestedJob?.id, requestedJob?.sequence]);
  const selected = jobs.find(job => job.id === selectedId);
  const visible = jobs.filter(job => filter === 'all' || (filter === 'active' ? active(job) : !active(job)));
  return <section className="preview-panel" aria-label="Jobs and diagnostics preview">
    <header><h2>Jobs & diagnostics</h2><p>Local labelled fixtures only. Disconnected: no runtime authority, network requests, job execution or research metrics. All reviews are examples, not submissions.</p></header>
    <div role="tablist" aria-label="Jobs and diagnostics views" className="preview-tabs">{[['journal', 'Job journal'], ['diagnostics', 'Developer diagnostics']].map(([id, label]) => <button key={id} type="button" role="tab" id={`${panelId}-${id}-tab`} aria-controls={`${panelId}-${id}`} aria-selected={tab === id} tabIndex={tab === id ? 0 : -1} onClick={() => setTab(id)} onKeyDown={event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 'journal' : event.key === 'End' ? 'diagnostics' : id === 'journal' ? 'diagnostics' : 'journal';
      setTab(next);
      event.currentTarget.parentElement?.querySelector<HTMLButtonElement>(`[id="${panelId}-${next}-tab"]`)?.focus();
    }}>{label}</button>)}</div>
    <section role="tabpanel" id={`${panelId}-journal`} aria-labelledby={`${panelId}-journal-tab`} hidden={tab !== 'journal'}>
    <label className="preview-field">Snapshot example state<select aria-label="Snapshot example state" value={snapshot} onChange={event => setSnapshot(event.target.value)}><option value="available">Available example snapshot</option><option value="unavailable">Unavailable / disconnected example</option><option value="empty">Empty example snapshot</option></select></label>
    <p aria-label="Snapshot cursor">Snapshot cursor: {snapshot === 'available' ? 'example-cursor-008' : snapshot === 'empty' ? 'example-cursor-000' : 'Unavailable'}. Static example, not a live event cursor.</p>
    {selectedId !== null && snapshot !== 'available' && <p aria-label="Requested job navigation" role="status">Requested job {selectedId}: details unavailable in the {snapshot} example snapshot. No outcome or authority is inferred.</p>}
    {snapshot === 'unavailable' ? <p className="preview-empty">Workspace snapshot unavailable. No live state or outcome is inferred.</p> : snapshot === 'empty' ? <p className="preview-empty">No example jobs in this snapshot.</p> : <>
      <label className="preview-field">Filter jobs<select aria-label="Filter jobs" value={filter} onChange={event => setFilter(event.target.value)}><option value="all">All</option><option value="active">Active</option><option value="terminal">Terminal</option></select></label>
      <p className="preview-muted">Active includes blocked and cleanup-pending. Terminal includes indeterminate: terminal does not mean successful.</p>
      <p className="preview-muted">Scroll the journal horizontally on narrow screens.</p>
      <div className="preview-ops-table-scroll" role="region" aria-label="Scrollable example job journal" tabIndex={0}><table aria-label="Example job journal"><thead><tr><th>Example job / kind</th><th>Status</th><th>Stage</th></tr></thead><tbody>{visible.map(job => <tr key={job.id}><td><button type="button" aria-label={`Inspect ${job.id}`} aria-pressed={selectedId === job.id} onClick={() => setSelectedId(job.id)}>{job.id}</button><div>{job.kind}</div></td><td>{statusLabel(job)}</td><td>{job.stage}</td></tr>)}</tbody></table></div>
      {selected && !visible.includes(selected) && <p>Selected job is outside this filter; its inspector remains bound to its exact ID.</p>}
      {selected ? <section className="preview-panel" aria-label="Exact example job inspector"><h3>Exact example job inspector</h3><dl className="preview-facts"><dt>Job ID</dt><dd>{selected.id}</dd><dt>Kind</dt><dd>{selected.kind}</dd><dt>Status</dt><dd>{statusLabel(selected)}</dd><dt>Current stage</dt><dd>{selected.stage}</dd><dt>Created</dt><dd>2026-01-12T09:00:00Z</dd><dt>Updated</dt><dd>2026-01-12T09:01:00Z</dd><dt>Owner session (example label)</dt><dd>example-owner</dd></dl><h4>Frozen inputs</h4><pre aria-label="Frozen job inputs">{json(selected.inputs)}</pre><h4>Job outcome</h4>{selected.result ? <pre aria-label="Example job result">{json(selected.result)}</pre> : <p>No completion result recorded.</p>}{selected.error && <p role="alert">{selected.error}</p>}{selected.status === 'indeterminate' && <p>Execution was interrupted without a verified outcome. This job will not be automatically replayed.</p>}{selected.status === 'cancel_requested' && <p>Cancellation requested; worker cleanup acknowledgment is pending. Not yet cancelled.</p>}<JobActions key={JSON.stringify([selected.id, requestedJob?.id, requestedJob?.sequence])} job={selected} onFreeze={setFrozenAction} hasFrozen={!!frozenAction} /></section> : selectedId !== null ? <p className="preview-empty" aria-label="Requested job navigation" role="status">Requested job {selectedId}: not found in the static example snapshot. Details unavailable; no other job was selected.</p> : <p className="preview-empty">Select a journal entry to inspect its exact example inputs and outcome.</p>}
    </>}
    {frozenAction && <section className="preview-panel" aria-label="Retained example job action"><h3>Frozen job action review — not sent</h3><p>{frozenAction.target.id === selectedId ? `Retained review targets ${frozenAction.target.id}.` : `Retained review targets ${frozenAction.target.id}, not the selected ${selectedId}.`} No job status changed; no authorization renewed.</p><pre aria-label="Frozen job action review">{json(frozenAction)}</pre><button type="button" onClick={() => setFrozenAction(null)}>Close frozen job action review</button></section>}
    </section>
    <section role="tabpanel" id={`${panelId}-diagnostics`} aria-labelledby={`${panelId}-diagnostics-tab`} hidden={tab !== 'diagnostics'}><DeveloperDiagnostics snapshot={snapshot} /></section>
  </section>;
}
