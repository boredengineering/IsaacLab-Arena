import { useState } from 'react';
import { skipToken, useMutation, useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { useRuntime } from './runtime';
import { isActive, isJob, type Job, type Workspace } from './contracts';
import { workspaceKey } from './cache';
interface Retained {
  payload: Record<string, unknown>;
  job?: Job;
}
/** Retain ambiguous submissions and accepted IDs without credentials or automatic replay. */
export function useEditorJob(kind: 'generate' | 'snapshots') {
  const runtime = useRuntime();
  const key = `arena:editor:${kind}:v1`;
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
    queryFn: () => runtime.api.get<Job>(`/jobs/${encodeURIComponent(retained!.job!.id)}`),
    enabled: !!retained?.job && !!runtime.session,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const job = observed ?? read.data ?? retained?.job;
  const submit = useMutation({
    retry: false,
    mutationFn: async (inputs: Record<string, unknown>) => {
      const next =
        retained && !retained.job
          ? retained
          : { payload: { ...inputs, idempotency_key: crypto.randomUUID() } };
      sessionStorage.setItem(key, JSON.stringify(next));
      setRetained(next);
      await runtime.api.activity();
      const accepted = await runtime.api.mutate<Job>(`/editor/${kind}`, next.payload);
      if (!isJob(accepted))
        throw new Error('Invalid job response; request retained for safe retry.');
      const saved = { ...next, job: accepted };
      sessionStorage.setItem(key, JSON.stringify(saved));
      setRetained(saved);
      void runtime.refresh();
      return accepted;
    },
  });
  return {
    job,
    submit,
    retained,
    busy: submit.isPending || (!!job && isActive(job)),
    error: submit.error ?? read.error,
    refresh: () => {
      void read.refetch();
      void runtime.refresh();
    },
  };
}
export function EditorJobProgress({ controller }: { controller: ReturnType<typeof useEditorJob> }) {
  const { job, error, retained, submit, refresh } = controller;
  return (
    <>
      {error && (
        <p className="notice error" role="alert">
          {error.message}
        </p>
      )}
      {retained && !job && !submit.isPending && (
        <p className="notice warning">
          Submission unresolved. Retry sends the same frozen inputs and key; it does not request a
          second job.
        </p>
      )}
      {job && (
        <div className="editor-job" role="status">
          <div className="section-heading">
            <strong>
              {job.kind === 'generate' ? 'Generation' : 'Snapshot render'} ·{' '}
              {job.status.replaceAll('_', ' ')}
            </strong>
            <Link to="/jobs/$jobId" params={{ jobId: job.id }}>
              Job details
            </Link>
          </div>
          <p>{job.stage}</p>
          {isActive(job) && <progress aria-label={`${job.kind} progress`} />}
          <button className="quiet" onClick={refresh}>
            Refresh job status
          </button>
          {job.error && <p className="error-text">{job.error}</p>}
          {job.status === 'indeterminate' && (
            <p>Execution was interrupted. No automatic retry or successful outcome is assumed.</p>
          )}
        </div>
      )}
    </>
  );
}
