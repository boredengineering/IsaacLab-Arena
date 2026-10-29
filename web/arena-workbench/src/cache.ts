import { notifyManager, type QueryClient } from '@tanstack/react-query';
import type { Workspace } from './contracts';
export const workspaceKey = ['workspace', 'default'] as const;
export const jobKey = (id: string) => ['workspace', 'default', 'job', id] as const;
export function publishSnapshot(cache: QueryClient, snapshot: Workspace) {
  notifyManager.batch(() => {
    cache.setQueryData(workspaceKey, snapshot);
    for (const job of snapshot.jobs) cache.setQueryData(jobKey(job.id), job);
  });
}
