import { expect, it } from 'vitest';
import type { Job } from './contracts';
import { snapshotHistorical, snapshotHistory, snapshotMatches, snapshotResult } from './snapshot-model';

function renderJob(id: string, hash: string, documentId = 'doc', updated = 1): Job {
  return {
    id, workspace_id: 'default', kind: 'snapshots', status: 'succeeded', stage: 'completed',
    created_at: 1, updated_at: updated, created_by_session_id: 'session', error: null,
    inputs: { document_id: documentId, canonical_hash: hash },
    result: {
      input_hash: 'source', warnings: [],
      assets: [{ id: 'cube', artifact_id: id, url: `/api/editor/artifacts/${id}` }],
      scene: { artifact_id: id, url: `/api/editor/artifacts/${id}` },
    },
  };
}

it('keeps historical asset freshness separate from canonical draft identity', () => {
  const receipt = snapshotHistory([renderJob('historical', 'current')], 'current', 'doc')[0];
  receipt.result.freshness = 'unverified_assets';
  expect(snapshotHistorical(receipt)).toBe(true);
  expect(snapshotMatches(receipt, 'current')).toBe(true);
  expect(snapshotMatches(receipt, 'changed')).toBe(false);
  expect(snapshotResult(receipt.result)).toBe(true);
  expect(snapshotResult({ ...receipt.result, freshness: 'unknown' })).toBe(false);
  receipt.result.freshness = 'verified_assets';
  expect(snapshotHistorical(receipt)).toBe(false);
  expect(snapshotHistorical(undefined)).toBe(false);
});

it('prefers the exact canonical scene over a newer different scene', () => {
  const history = snapshotHistory([
    renderJob('matching', 'current', 'previous-frozen-view', 1),
    renderJob('newer', 'other-scene', 'doc', 9),
    renderJob('unrelated', 'other-scene', 'another-doc', 10),
  ], 'current', 'doc');
  expect(history.map((receipt) => receipt.jobId)).toEqual(['matching', 'newer']);
  expect(snapshotMatches(history[0], 'current')).toBe(true);
  expect(snapshotMatches(history[1], 'current')).toBe(false);
});

it('never calls a previous render current while validation is pending or changed', () => {
  const history = snapshotHistory([renderJob('old', 'old-scene')], null, 'doc');
  expect(history).toHaveLength(1);
  expect(snapshotMatches(history[0], null)).toBe(false);
  expect(snapshotMatches(history[0], 'changed-scene')).toBe(false);
  expect(snapshotHistory([renderJob('unrelated', 'old-scene', 'different-doc')], 'current', 'doc')).toEqual([]);
});

it('ignores failed renders and malformed receipts', () => {
  const failed = { ...renderJob('failed', 'current'), status: 'failed' as const };
  const malformed = renderJob('malformed', 'current');
  malformed.result = { input_hash: 'source', assets: [null], scene: null, warnings: [] };
  expect(snapshotHistory([failed, malformed], 'current', 'doc')).toEqual([]);
});

it('deduplicates repeated scenes, caps history, and keeps the matching scene before truncation', () => {
  const jobs = Array.from({ length: 12 }, (_, i) => renderJob(`job-${i}`, `scene-${i}`, 'doc', i));
  jobs.push(renderJob('replacement', 'scene-0', 'doc', 0.5));
  const history = snapshotHistory(jobs, 'scene-0', 'doc');
  expect(history).toHaveLength(8);
  expect(history[0].jobId).toBe('replacement');
  expect(new Set(history.map((receipt) => receipt.canonicalHash)).size).toBe(history.length);
});
