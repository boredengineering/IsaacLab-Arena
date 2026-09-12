import type { Job } from './contracts';
import type { SnapshotResult } from './editor-contracts';

export interface SnapshotReceipt {
  jobId: string;
  documentId?: string;
  canonicalHash: string | null;
  result: SnapshotResult;
}

export function snapshotHistorical(receipt: SnapshotReceipt | undefined) {
  return receipt?.result.freshness === 'unverified_assets';
}

export function snapshotResult(value: unknown): value is SnapshotResult {
  const record = (item: unknown): item is Record<string, unknown> => !!item && typeof item === 'object' && !Array.isArray(item);
  const artifact = (item: unknown): boolean => record(item) && typeof item.artifact_id === 'string' && typeof item.url === 'string';
  const variant = (item: unknown): boolean => record(item) && artifact(item) && typeof item.width === 'number' && Number.isFinite(item.width) && item.width > 0
    && typeof item.height === 'number' && Number.isFinite(item.height) && item.height > 0;
  const image = (item: unknown): boolean => record(item) && artifact(item) && (item.variants === undefined
    || (record(item.variants) && variant(item.variants.thumbnail) && variant(item.variants.full)));
  return record(value)
    && (value.input_hash === undefined || typeof value.input_hash === 'string')
    && (value.freshness === undefined || value.freshness === 'verified_assets' || value.freshness === 'unverified_assets')
    && Array.isArray(value.assets) && value.assets.every((item) => record(item) && image(item) && typeof item.id === 'string'
      && (item.dimensions_m === undefined || (Array.isArray(item.dimensions_m) && item.dimensions_m.length === 3
        && item.dimensions_m.every((dimension: unknown) => typeof dimension === 'number' && Number.isFinite(dimension)))))
    && (value.scene === null || image(value.scene))
    && Array.isArray(value.warnings) && value.warnings.every((warning) => typeof warning === 'string')
    && (value.errors === undefined || (Array.isArray(value.errors) && value.errors.every((error) => record(error)
      && ['id', 'stage', 'code', 'message'].every((key) => typeof error[key] === 'string'))))
    && (value.partial === undefined || typeof value.partial === 'boolean')
    && (value.timings === undefined || (record(value.timings) && Object.values(value.timings).every((time) => typeof time === 'number' && Number.isFinite(time))));
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

/** Canonical draft identity only; asset freshness is a separate receipt property. */
export function snapshotMatches(receipt: SnapshotReceipt | undefined, canonicalHash: string | null) {
  return !!canonicalHash && receipt?.canonicalHash === canonicalHash;
}
