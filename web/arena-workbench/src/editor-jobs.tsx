import { useLayoutEffect, useRef, useState } from 'react';
import { skipToken, useMutation, useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { useRuntime } from './runtime';
import { isActive, isJob, type Job, type Workspace } from './contracts';
import { workspaceKey } from './cache';
import { GenerationReauthorization, isBlockedGeneration } from './generation-reauthorization';
import { GenerationDiagnostic } from './generation-diagnostic';
import { parseGraphRenderer } from './graph-host';

// Router search reducers can receive unvalidated URL fields as well as route state.
function jobLinkSearch(previous: Record<string, unknown>) {
  return {
    filter: previous.filter === 'active' || previous.filter === 'terminal' ? previous.filter : 'all',
    ...(previous.graphRenderer === undefined ? {} : { graphRenderer: parseGraphRenderer(previous.graphRenderer) }),
    ...(previous.layout === undefined ? {} : { layout: previous.layout === 'v7' ? 'v7' : 'legacy' }),
  };
}
interface Retained {
  payload: Record<string, unknown>;
  job?: Job;
}
function guarded(current: () => boolean, run: () => Promise<Job | undefined>) {
  return async () => {
    try { return await run(); }
    catch (error) { if (current()) throw error; }
  };
}
/** Retain ambiguous submissions and accepted IDs without credentials or automatic replay. */
export function useEditorJob(kind: 'generate' | 'snapshots' | 'build' | 'evaluate') {
  const runtime = useRuntime();
  // Authority belongs to the rendered controls, not a later click's API session.
  const generation = runtime.api.sessionGeneration;
  const key = `arena:editor:${kind}:v1`;
  const scope = useRef(0);
  const operation = useRef(0);
  useLayoutEffect(() => {
    scope.current++;
    return () => { scope.current++; };
  }, [runtime.api, runtime.session?.session_id, generation, kind]);
  function ownership() {
    const api = runtime.api;
    const sessionId = runtime.session?.session_id;
    const token = scope.current;
    return () => !!sessionId && scope.current === token && api.sessionGeneration === generation
      && api.session?.session_id === sessionId;
  }
  const [discardError, setDiscardError] = useState<Error | null>(null);
  const [retained, setRetained] = useState<Retained | null>(() => {
    try {
      const raw = sessionStorage.getItem(key);
      if (!raw) return null;
      const value = JSON.parse(raw) as Retained;
      return value.payload && typeof value.payload.idempotency_key === 'string' ? value : null;
    } catch {
      return null;
    }
  });
  const { data: workspace } = useQuery<Workspace>({
    queryKey: workspaceKey,
    queryFn: skipToken,
    staleTime: Infinity,
  });
  const observed = workspace?.jobs.find((job) => job.id === retained?.job?.id);
  const read = useQuery({
    queryKey: ['editor-job', retained?.job?.id, runtime.session?.session_id],
    queryFn: async () => {
      const current = ownership();
      const id = retained!.job!.id;
      if (!current()) throw new Error('Session changed; refresh explicitly.');
      const result = await runtime.api.get<Job>(`/jobs/${encodeURIComponent(id)}`);
      if (!current() || !isJob(result) || result.id !== id) throw new Error('Job read is no longer current.');
      return result;
    },
    enabled: !!retained?.job && !!runtime.session,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const job = observed ?? read.data ?? retained?.job;
  const submitMutation = useMutation({
    retry: false,
    mutationFn: (run: () => Promise<Job | undefined>) => run(),
  });
  function submission(inputs: Record<string, unknown>, canDispatch = () => true) {
    const ownsSession = ownership();
    const token = ++operation.current;
    const current = () => ownsSession() && operation.current === token;
    const api = runtime.api;
    const refresh = runtime.refresh;
    const next = retained && !retained.job ? retained
      : { payload: structuredClone({ ...inputs, idempotency_key: crypto.randomUUID() }) };
    return guarded(current, async () => {
      if (!current() || !canDispatch()) return;
      sessionStorage.setItem(key, JSON.stringify(next));
      setRetained(next);
      await api.activity();
      if (!current() || !canDispatch()) return;
      // Visibility can retire automatic dispatch, never an already accepted job.
      const accepted = await api.mutate<Job>(`/editor/${kind}`, next.payload);
      if (!current()) return;
      if (!isJob(accepted) || kind === 'evaluate' && accepted.kind !== 'evaluate')
        throw new Error('Invalid job response; request retained for safe retry.');
      const saved = { ...next, job: accepted };
      sessionStorage.setItem(key, JSON.stringify(saved));
      setRetained(saved);
      void refresh();
      return accepted;
    });
  }
  const submit = { ...submitMutation,
    mutate: (inputs: Record<string, unknown>, canDispatch?: () => boolean) => { if (ownership()()) submitMutation.mutate(submission(inputs, canDispatch)); },
    mutateAsync: (inputs: Record<string, unknown>, canDispatch?: () => boolean) => ownership()()
      ? submitMutation.mutateAsync(submission(inputs, canDispatch)) : Promise.resolve(undefined),
  };
  const cancelMutation = useMutation({
    retry: false,
    mutationFn: (run: () => Promise<Job | undefined>) => run(),
  });
  function cancellation(jobId: string) {
    const current = ownership();
    const api = runtime.api;
    const refresh = runtime.refresh;
    const refetch = read.refetch;
    return guarded(current, async () => {
      if (!current()) return;
      await api.activity();
      if (!current()) return;
      await api.mutate(`/jobs/${encodeURIComponent(jobId)}/cancel`, {});
      if (!current()) return;
      const verified = await api.get<Job>(`/jobs/${encodeURIComponent(jobId)}`);
      if (!current()) return;
      if (!isJob(verified) || verified.id !== jobId) throw new Error('Invalid cancellation status response');
      if (retained?.job?.id === jobId) void refetch();
      void refresh();
      return verified;
    });
  }
  const cancel = { ...cancelMutation,
    mutate: (jobId: string) => { if (ownership()()) cancelMutation.mutate(cancellation(jobId)); },
    mutateAsync: (jobId: string) => ownership()()
      ? cancelMutation.mutateAsync(cancellation(jobId)) : Promise.resolve(undefined),
  };
  return {
    kind,
    job,
    blockingJobs: kind === 'generate' ? (workspace?.jobs.filter(isBlockedGeneration) ?? []) : [],
    submit,
    cancel,
    retained,
    discard: () => {
      if (!retained || job || submit.isPending) return;
      try {
        sessionStorage.removeItem(key);
        setRetained(null);
        setDiscardError(null);
        submit.reset();
      } catch {
        setDiscardError(new Error('Could not clear local retry information. The request is still retained.'));
      }
    },
    busy: submit.isPending || (!!job && (isActive(job) || isBlockedGeneration(job)))
      || (kind === 'generate' && !!workspace?.jobs.some(isBlockedGeneration))
      || (kind === 'snapshots' && !!workspace?.jobs.some((entry) => entry.kind === 'snapshots' && isActive(entry))),
    error: discardError ?? submit.error ?? cancel.error ?? read.error,
    refresh: () => {
      if (retained?.job) void read.refetch();
      void runtime.refresh();
    },
  };
}
export function EditorJobProgress({ controller }: { controller: ReturnType<typeof useEditorJob> }) {
  const { job, error, retained, submit, cancel, refresh, discard } = controller;
  const [reviewId, setReviewId] = useState<string | null>(null);
  const blockers = controller.blockingJobs.filter(entry => entry.id !== job?.id);
  const review = blockers.find(entry => entry.id === reviewId);
  return (
    <>
      {blockers.length > 0 && <section aria-label="Blocking generations">
        <p>These generations require an explicit decision before starting another.</p>
        <ul>{blockers.map(entry => <li key={entry.id}>
          <button type="button" onClick={() => setReviewId(entry.id)}>Review blocked generation {entry.id}</button>
        </li>)}</ul>
        {review && <div key={review.id}>
          <Link to="/jobs/$jobId" params={{ jobId: review.id }} search={jobLinkSearch}>Job details</Link>
          <GenerationReauthorization job={review} onVerified={refresh} />
          <button className="danger" disabled={cancel.isPending} onClick={() => cancel.mutate(review.id)}>Cancel generation</button>
        </div>}
      </section>}
      {error && (
        <p className="notice error" role="alert">
          {error.message}
        </p>
      )}
      {retained && !job && !submit.isPending && (
        <div className="notice warning">
          <p>{controller.kind === 'generate'
            ? 'Submission unresolved. Retry sends the same frozen inputs, credential reference and request ID. A replacement API key is never substituted automatically.'
            : 'Submission unresolved. Retry sends the same frozen inputs and request ID.'}</p>
          <button type="button" onClick={() => {
            if (window.confirm('A job may already have been accepted. Check the job journal before starting another. Discard only this tab’s retry information?')) discard();
          }}>Discard unresolved request</button>
        </div>
      )}
      {job && (
        <div className="editor-job" role="status">
          <div className="section-heading">
            <strong>
              {job.kind === 'generate' ? 'Generation' : job.kind === 'evaluate' ? 'Policy evaluation' : job.kind === 'build' ? 'Build environment' : job.kind === 'snapshots' ? 'Snapshot render' : job.kind} ·{' '}
              {job.status.replaceAll('_', ' ')}
            </strong>
            <Link to="/jobs/$jobId" params={{ jobId: job.id }} search={jobLinkSearch}>
              Job details
            </Link>
          </div>
          <p>{job.stage}</p>
          {isBlockedGeneration(job) && <GenerationReauthorization key={`${job.id}`} job={job} onVerified={refresh} />}
          {isActive(job) && <progress aria-label={`${job.kind} progress`} />}
          {(['queued', 'running'].includes(job.status) || isBlockedGeneration(job)) && <button className="danger" disabled={cancel.isPending} onClick={() => cancel.mutate(job.id)}>
            {cancel.isPending ? 'Requesting cancellation…' : job.kind === 'evaluate' ? 'Cancel evaluation' : job.kind === 'snapshots' ? 'Cancel snapshot render' : job.kind === 'build' ? 'Cancel build' : job.kind === 'generate' ? 'Cancel generation' : 'Cancel job'}
          </button>}
          {job.status === 'cancel_requested' && <p>Cancellation requested; waiting for worker acknowledgment.</p>}
          {['cancelled', 'indeterminate', 'failed'].includes(job.status) && job.execution?.outcome === 'unknown' &&
            <p className="notice warning">External execution outcome is unknown. Stopping the local worker does not prove the provider did no work. No automatic retry will be made.</p>}
          {job.status === 'cancelled' && job.execution?.outcome === 'candidate_accepted' &&
            <p className="notice warning">An accepted candidate was preserved for review. The cancelled job is not a successful workflow.</p>}
          {job.status === 'cancelled' && job.execution?.outcome === 'not_released' &&
            <p>Cancelled before external work was released.</p>}
          <button className="quiet" onClick={refresh}>
            Refresh job status
          </button>
          {job.error && <p className="error-text">{job.error}</p>}
          {job.kind === 'generate' && <GenerationDiagnostic value={job.diagnostic} />}
          {job.status === 'indeterminate' && (
            <p>No verified completion was recorded. {job.kind === 'generate' && !job.diagnostic ? 'A specific cause was not retained for this attempt. ' : ''}No automatic retry or successful outcome is assumed.</p>
          )}
        </div>
      )}
    </>
  );
}
