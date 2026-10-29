import { expect, it } from 'vitest';
import { isActive, isEvent, isJob, isWorkspace } from './contracts';

it('retains authorization-blocked work in snapshots/events without treating it as executing', () => {
  const job = { id: 'blocked', workspace_id: 'default', kind: 'generate', status: 'blocked_authorization', stage: 'blocked_authorization', inputs: {} };
  expect(isJob(job)).toBe(true);
  expect(isWorkspace({ id: 'default', name: 'Test', jobs: [job], event_cursor: 1 })).toBe(true);
  expect(isEvent({ schema_version: 1, id: 1, workspace_id: 'default', job_id: job.id, kind: 'blocked', job })).toBe(true);
  if (isJob(job)) expect(isActive(job)).toBe(false);
});

it.each([
  null,
  { released: 'true', candidate_accepted: false, outcome: 'unknown' },
  { released: false, candidate_accepted: false, outcome: 'unknown' },
  { released: true, candidate_accepted: true, outcome: 'not_released' },
  { released: true, candidate_accepted: false, outcome: 'success' },
])('rejects inconsistent execution evidence %j', execution => {
  expect(isJob({ id: 'cancelled', workspace_id: 'default', kind: 'generate', status: 'cancelled', stage: 'cancelled', inputs: {}, execution })).toBe(false);
});
