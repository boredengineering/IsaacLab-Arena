import { useLayoutEffect, useMemo } from 'react';
import { skipToken, useMutation, useQuery } from '@tanstack/react-query';
import { workspaceKey } from './cache';
import type { Workspace } from './contracts';
import { useRuntime } from './runtime';

const uncertainResume = 'Queue resume acknowledgement unavailable. Inspect jobs before a manual retry; the shared queue may already be running. No automatic retry was sent.';

/** Explicit global queue admission, independent of diagnostic job submission. */
export function QueueResume() {
  const runtime = useRuntime();
  const { data: workspace } = useQuery<Workspace>({
    queryKey: workspaceKey,
    queryFn: skipToken,
    staleTime: Infinity,
  });
  const queued = workspace?.jobs.filter(job => job.status === 'queued') ?? [];
  const kinds = new Map<string, number>();
  for (const job of queued) kinds.set(job.kind, (kinds.get(job.kind) ?? 0) + 1);
  const resumeGeneration = runtime.api.sessionGeneration;
  const enabled = !!runtime.session && queued.length > 0;
  const resumeOwner = useMemo(() => ({ active: false, epoch: 0, busy: false }),
    [runtime.api, resumeGeneration, runtime.session?.session_id, enabled]);
  useLayoutEffect(() => {
    resumeOwner.active = true;
    resumeOwner.epoch++;
    return () => { resumeOwner.active = false; resumeOwner.epoch++; };
  }, [resumeOwner]);
  const resume = useMutation({
    retry: false,
    mutationFn: (request: { current(): boolean; run(): Promise<boolean> }) => request.run(),
  });
  function resumeQueue() {
    const api = runtime.api;
    const sessionId = runtime.session?.session_id;
    const epoch = resumeOwner.epoch;
    const refresh = runtime.refresh;
    const current = () => enabled && resumeOwner.active && resumeOwner.epoch === epoch
      && !!sessionId && api.session?.session_id === sessionId && api.sessionGeneration === resumeGeneration;
    if (!current() || resumeOwner.busy) return;
    // Lock before confirmation and React Query's deferred mutation dispatch.
    resumeOwner.busy = true;
    if (!window.confirm('Resume the entire shared workload queue? This may start generation and GPU jobs, including jobs not shown in this snapshot.') || !current()) {
      resumeOwner.busy = false;
      return;
    }
    resume.mutate({ current, run: async () => {
      let dispatched = false;
      try {
        if (!current()) return false;
        await api.activity();
        if (!current()) return false;
        dispatched = true;
        const result = await api.mutate<{ resumed: boolean }>('/jobs/resume-queue', {});
        if (!current()) return false;
        if (result?.resumed !== true) throw new Error(uncertainResume);
        await refresh();
        return current();
      } catch {
        // Never publish raw transport or server errors into UI/mutation caches.
        if (current()) throw new Error(dispatched ? uncertainResume : 'Session activity could not be verified. Queue resume was not sent. Reconnect or inspect jobs before trying again.');
        return false;
      } finally {
        resumeOwner.busy = false;
      }
    } });
  }
  if (!queued.length) return null;
  return <section className="notice warning" aria-label="Shared workload queue">
    <strong>Observed queued jobs: {queued.length} ({[...kinds].map(([kind, count]) => `${kind}: ${count}`).join(', ')})</strong>
    <p>Queued jobs do not prove the queue is paused. This snapshot may be stale.</p>
    <p>This resumes the entire shared workload queue, including jobs not shown in this snapshot. Generation and GPU jobs may start.</p>
    <button type="button" disabled={!enabled || resume.isPending} onClick={resumeQueue}>Resume queue</button>
    {resume.error && resume.variables?.current() && <p role="alert" className="error-text">{resume.error.message}</p>}
    {resume.isSuccess && resume.data === true && resume.variables?.current() && <p role="status">Queue resume acknowledged. Observe each job for its outcome.</p>}
  </section>;
}
