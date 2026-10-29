import { describe, expect, it } from 'vitest';
import { Reconciler } from './reconcile';
import { QueryClient } from '@tanstack/react-query';
import { publishSnapshot, workspaceKey, jobKey } from './cache';
const job = (status = 'running') => ({
  id: 'j1',
  workspace_id: 'default',
  kind: 'diagnostic',
  status,
  stage: status,
  created_at: 1,
  updated_at: 2,
  inputs: { steps: 2, delay_seconds: 1 },
  result: null,
  error: null,
  created_by_session_id: 's1',
});
const event = (id: number, status = 'running') => ({
  schema_version: 1,
  id,
  workspace_id: 'default',
  job_id: 'j1',
  kind: 'stage_changed',
  job: job(status),
});
describe('snapshot and journal reconciliation', () => {
  it('recovers gaps from a snapshot, rejects malformed events, and updates exact Query keys', () => {
    const state = new Reconciler();
    const cache = new QueryClient();
    cache.setQueryData(['unrelated'], 'keep');
    state.snapshot({ id: 'default', name: 'Arena workspace', jobs: [job()], event_cursor: 10 });
    state.event(event(12, 'succeeded'));
    expect(state.needsResync).toBe(true);
    expect(state.value?.jobs[0].status).toBe('running');
    state.snapshot({ id: 'default', name: 'Arena workspace', jobs: [job()], event_cursor: 11 });
    expect(state.needsResync).toBe(false);
    publishSnapshot(cache, state.value!);
    expect(cache.getQueryData(workspaceKey)).toEqual(state.value);
    expect(cache.getQueryData(jobKey('j1'))).toEqual(state.value?.jobs[0]);
    expect(cache.getQueryData(['unrelated'])).toBe('keep');
    state.event({ ...event(13), schema_version: 2 });
    expect(state.needsResync).toBe(true);
    expect(state.value?.event_cursor).toBe(12);
  });
  it('bounds events buffered by a slow snapshot consumer', () => {
    const state = new Reconciler();
    for (let id = 1; id <= 1000; id++) state.event(event(id));
    expect(state.bufferedCount).toBeLessThanOrEqual(256);
    expect(state.needsResync).toBe(true);
    state.snapshot({
      id: 'default',
      name: 'Arena workspace',
      jobs: [job('succeeded')],
      event_cursor: 1000,
    });
    expect(state.needsResync).toBe(false);
    expect(state.bufferedCount).toBe(0);
  });
  it('buffers before snapshot and never regresses on duplicate or old replay', () => {
    const state = new Reconciler();
    state.event(event(12, 'succeeded'));
    state.event(event(11));
    state.snapshot({ id: 'default', name: 'Arena workspace', jobs: [job()], event_cursor: 10 });
    expect(state.value?.event_cursor).toBe(12);
    expect(state.value?.jobs[0].status).toBe('succeeded');
    state.event(event(11));
    expect(state.value?.jobs[0].status).toBe('succeeded');
    state.snapshot({ id: 'default', name: 'Arena workspace', jobs: [job()], event_cursor: 10 });
    expect(state.value?.jobs[0].status).toBe('succeeded');
  });
});
