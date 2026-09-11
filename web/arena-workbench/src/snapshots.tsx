import { useEffect, useRef, useState } from 'react';
import type { Asset, SnapshotResult } from './editor-contracts';
import { EditorJobProgress, useEditorJob } from './editor-jobs';
export interface SnapshotReceipt {
  jobId: string;
  text: string;
  documentId?: string;
  result: SnapshotResult;
}
export function useSnapshots() {
  const controller = useEditorJob('snapshots');
  const [history, setHistory] = useState<SnapshotReceipt[]>([]);
  useEffect(() => {
    const job = controller.job;
    if (job?.status !== 'succeeded' || !job.result || !Array.isArray(job.result.assets)) return;
    const receipt = {
      jobId: job.id,
      text: String(controller.retained?.payload.yaml_text ?? ''),
      documentId: controller.retained?.payload.document_id as string | undefined,
      result: job.result as unknown as SnapshotResult,
    };
    setHistory((previous) =>
      previous.some((r) => r.jobId === job.id) ? previous : [receipt, ...previous].slice(0, 8),
    );
  }, [controller.job, controller.retained]);
  return { controller, history };
}
export function SnapshotImage({ url, label }: { url: string; label: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);
  if (!/^\/api\/editor\/artifacts\/[a-zA-Z0-9_.-]+$/.test(url))
    return <p className="error-text">Unsupported artifact URL.</p>;
  return (
    <>
      {failed ? (
        <div className="asset-placeholder">Image unavailable. Check artifact access.</div>
      ) : (
        <button
          className="snapshot-image"
          aria-label={`Zoom ${label}`}
          onClick={() => dialog.current?.showModal()}
        >
          <img src={url} alt={label} loading="lazy" onError={() => setFailed(true)} />
        </button>
      )}
      <dialog className="zoom-dialog" aria-label={`Zoomed ${label}`} ref={dialog}>
        <div className="section-heading">
          <h3>{label}</h3>
          <button onClick={() => dialog.current?.close()}>Close image</button>
        </div>
        <img src={url} alt={`Zoomed ${label}`} />
      </dialog>
    </>
  );
}
export function AssetGrid({
  assets,
  receipt,
  stale,
}: {
  assets: Asset[];
  receipt?: SnapshotReceipt;
  stale: boolean;
}) {
  return (
    <div className="asset-grid">
      {assets.map((asset) => {
        const image = receipt?.result.assets.find((a) => a.id === asset.id);
        return (
          <article className="asset-card" key={asset.id}>
            {image ? (
              <SnapshotImage url={image.url} label={`${asset.id} snapshot`} />
            ) : (
              <div className="asset-placeholder">Not rendered</div>
            )}
            <div className="asset-caption">
              <span className="asset-role">{asset.role}</span>
              <strong>{asset.id}</strong>
              <p>{asset.registry_name}</p>
              {image && stale && <p className="stale-label">Stale · draft changed</p>}
              {asset.parent_id && <small>Parent: {asset.parent_id}</small>}
              {asset.prim_path && <code>{asset.prim_path}</code>}
              {image?.dimensions_m && (
                <small>Dimensions (m): {image.dimensions_m.join(' × ')}</small>
              )}
            </div>
          </article>
        );
      })}
    </div>
  );
}
export function SnapshotGallery({
  snapshots,
  draft,
  documentId,
  enabled,
}: {
  snapshots: ReturnType<typeof useSnapshots>;
  draft: string;
  documentId: string;
  enabled: boolean;
}) {
  return (
    <section className="snapshot-section">
      <div className="section-heading">
        <h2>Scene snapshots</h2>
        <button
          disabled={!enabled || snapshots.controller.busy}
          onClick={() =>
            snapshots.controller.submit.mutate({
              yaml_text: draft,
              ...(documentId ? { document_id: documentId } : {}),
            })
          }
        >
          {snapshots.controller.submit.isPending
            ? 'Submitting render…'
            : snapshots.controller.retained && !snapshots.controller.job
              ? 'Retry snapshot request'
              : 'Render snapshots'}
        </button>
      </div>
      <p className="hint">
        Explicit Isaac Sim render · scene overview and per-asset thumbnails. No simulation starts
        while typing.
      </p>
      <EditorJobProgress controller={snapshots.controller} />
      {!snapshots.history.length ? (
        <div className="empty-state">
          No snapshots rendered. Rendering is an explicit GPU job, never a side effect of editing.
        </div>
      ) : (
        <div className="scene-gallery">
          {snapshots.history.map((receipt) => (
            <figure key={receipt.jobId}>
              {receipt.result.scene ? (
                <SnapshotImage
                  url={receipt.result.scene.url}
                  label={`scene snapshot ${receipt.jobId}`}
                />
              ) : (
                <p className="empty-state">No scene image returned.</p>
              )}
              <figcaption>
                <strong>Scene overview</strong>
                <p
                  className={
                    receipt.text !== draft || receipt.documentId !== documentId
                      ? 'stale-label'
                      : 'muted'
                  }
                >
                  {receipt.text !== draft || receipt.documentId !== documentId
                    ? 'Stale · draft changed since this render'
                    : 'Matches current draft'}
                </p>
                <details>
                  <summary>Render receipt</summary>
                  <code>{receipt.result.input_hash}</code>
                  {receipt.result.warnings.map((warning, i) => (
                    <p key={i}>{warning}</p>
                  ))}
                </details>
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </section>
  );
}
