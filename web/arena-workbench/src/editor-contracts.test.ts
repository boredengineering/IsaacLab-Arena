import { expect, it } from 'vitest';
import { isJob, isWorkspace } from './contracts';
it('accepts editor jobs in durable workspace observation without diagnostic-only inputs', () => {
  const job = {
    id: 'render-1',
    workspace_id: 'default',
    kind: 'snapshots',
    stage: 'rendering',
    status: 'running',
    inputs: { yaml_text: 'env_name: test' },
  };
  expect(isJob(job)).toBe(true);
  expect(isWorkspace({ id: 'default', name: 'Arena', jobs: [job], event_cursor: 1 })).toBe(true);
  expect(isJob({ ...job, inputs: null })).toBe(false);
});
