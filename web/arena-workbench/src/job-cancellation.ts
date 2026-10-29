import { useLayoutEffect, useMemo } from 'react';
import { useMutation } from '@tanstack/react-query';
import { isJob } from './contracts';
import { useRuntime } from './runtime';

interface Cancellation {
  owner: object;
  current(): boolean;
  run(): Promise<void>;
}

/** Request cancellation without creating a second job/authoring observer. */
export function useJobCancellation(jobId: string | undefined) {
  const runtime = useRuntime();
  const api = runtime.api;
  const sessionId = runtime.session?.session_id;
  const generation = api.sessionGeneration;
  const owner = useMemo(() => ({ active: false, epoch: 0 }), [jobId, api, sessionId, generation]);
  useLayoutEffect(() => {
    owner.active = true;
    owner.epoch++;
    return () => { owner.active = false; owner.epoch++; };
  }, [owner]);
  const mutation = useMutation({
    retry: false,
    mutationFn: (request: Cancellation) => request.run(),
  });
  function mutate() {
    if (!jobId) return;
    // Capture click ownership before React Query can defer mutationFn.
    const epoch = owner.epoch;
    const refresh = runtime.refresh;
    const current = () => owner.active && owner.epoch === epoch && !!sessionId
      && api.session?.session_id === sessionId && api.sessionGeneration === generation;
    mutation.mutate({ owner, current, run: async () => {
      try {
        if (!current()) return;
        await api.activity();
        if (!current()) return;
        const accepted = await api.mutate(`/jobs/${encodeURIComponent(jobId)}/cancel`, {});
        if (!current()) return;
        if (!isJob(accepted) || accepted.id !== jobId) throw new Error('Invalid cancellation status response');
        // cancel_requested is an acknowledgement, not terminal job success.
        await refresh();
      } catch (error) {
        if (current()) throw error;
      }
    } });
  }
  const current = mutation.variables?.owner === owner && mutation.variables.current();
  return { cancel: {
    mutate,
    isPending: current && mutation.isPending,
    error: current ? mutation.error : null,
  } };
}
