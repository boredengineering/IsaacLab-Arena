import type { Job } from './contracts';
import type { SnapshotResult } from './editor-contracts';

export interface SnapshotReceipt {
  jobId: string;
  documentId?: string;
  canonicalHash: string | null;
  result: SnapshotResult;
}

function snapshotResult(value: Job['result']): value is Job['result'] & SnapshotResult {
  if (!value || typeof value.input_hash !== 'string') return false;
  const artifact = (item: unknown): boolean => {
    if (!item || typeof item !== 'object') return false;
    const entry = item as Record<string, unknown>;
    return typeof entry.artifact_id === 'string' && typeof entry.url === 'string';
  };
  return Array.isArray(value.assets)
    && value.assets.every((item) => artifact(item) && typeof item.id === 'string'
      && (item.dimensions_m === undefined || (Array.isArray(item.dimensions_m)
        && item.dimensions_m.every((dimension: unknown) => typeof dimension === 'number' && Number.isFinite(dimension)))))
    && (value.scene === null || artifact(value.scene))
    && Array.isArray(value.warnings) && value.warnings.every((warning) => typeof warning === 'string');
}

/** Recover server receipts; asset IDs alone never establish scene identity. */
export function snapshotHistory(jobs: Job[], canonicalHash: string | null, documentId: string): SnapshotReceipt[] {
  const updated = (job: Job) => (typeof job.updated_at === 'number'
    ? job.updated_at : Date.parse(job.updated_at) / 1000) || 0;
  const unique = [...new Map(jobs.map((job) => [job.id, job])).values()]
    .filter((job) => job.kind === 'snapshots' && job.status === 'succeeded' && snapshotResult(job.result))
    .sort((a, b) => updated(b) - updated(a));
  const seen = new Set<string>();
  const receipts: SnapshotReceipt[] = [];
  for (const job of unique) {
    const hash = typeof job.inputs.canonical_hash === 'string' ? job.inputs.canonical_hash : null;
    const source = typeof job.inputs.document_id === 'string' ? job.inputs.document_id : undefined;
    if (!(canonicalHash && hash === canonicalHash) && !(documentId && source === documentId)) continue;
    const identity = hash ?? job.id;
    if (seen.has(identity)) continue;
    seen.add(identity);
    receipts.push({ jobId: job.id, documentId: source, canonicalHash: hash, result: job.result as unknown as SnapshotResult });
  }
  return receipts.sort((a, b) => Number(b.canonicalHash === canonicalHash && !!canonicalHash)
    - Number(a.canonicalHash === canonicalHash && !!canonicalHash)).slice(0, 8);
}

export function snapshotMatches(receipt: SnapshotReceipt | undefined, canonicalHash: string | null) {
  return !!canonicalHash && receipt?.canonicalHash === canonicalHash;
}
