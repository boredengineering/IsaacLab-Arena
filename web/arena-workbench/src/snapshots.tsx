import { useEffect, useMemo, useRef, useState } from 'react';
import { skipToken, useQuery } from '@tanstack/react-query';
import type { Asset } from './editor-contracts';
import type { Workspace } from './contracts';
import { workspaceKey } from './cache';
import { snapshotHistory, snapshotMatches, type SnapshotReceipt } from './snapshot-model';
import { useEditorJob } from './editor-jobs';
export function useSnapshots(canonicalHash: string | null, documentId: string) {
  const controller = useEditorJob('snapshots');
  const { data: workspace } = useQuery<Workspace>({
    queryKey: workspaceKey, queryFn: skipToken, gcTime: Infinity,
  });
  const history = useMemo(() => snapshotHistory(
    [...(workspace?.jobs ?? []), ...(controller.job ? [controller.job] : [])],
    canonicalHash, documentId,
  ), [workspace, controller.job, canonicalHash, documentId]);
  return { controller, history };
}
export function SnapshotImage({ url, label }: { url: string; label: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [failed, setFailed] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  useEffect(() => {
    setFailed(false);
    setZoomed(false);
    dialog.current?.close();
  }, [url]);
  if (!/^\/api\/editor\/artifacts\/[a-zA-Z0-9_.-]+$/.test(url))
    return <p className="error-text">Unsupported artifact URL.</p>;
  return (
    <>
      {failed ? (
        <div className="asset-placeholder image-error" role="alert">
          <span>Image unavailable. Retry after reconnecting, or render snapshots again.</span>
          <button aria-label={`Retry ${label}`} onClick={() => setFailed(false)}>Retry image</button>
        </div>
      ) : (
        <button
          className="snapshot-image"
          aria-label={`Zoom ${label}`}
          onClick={() => { setZoomed(true); dialog.current?.showModal(); }}
        >
          <img src={url} alt={label} loading="lazy" onError={() => setFailed(true)} />
        </button>
      )}
      <dialog className="zoom-dialog" aria-label={`Zoomed ${label}`} ref={dialog} onClose={() => setZoomed(false)}>
        <div className="section-heading">
          <h3>{label}</h3>
          <button onClick={() => { dialog.current?.close(); setZoomed(false); }}>Close image</button>
        </div>
        {zoomed && <img src={url} alt={`Zoomed ${label}`} onError={() => {
          setFailed(true); setZoomed(false); dialog.current?.close();
        }} />}
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
              <div className="asset-placeholder">
                {asset.role === 'embodiment' ? 'Scene preview only' : 'No saved preview'}
              </div>
            )}
            <div className="asset-caption">
              <span className="asset-role">{asset.role}</span>
              <strong>{asset.id}</strong>
              <p>{asset.registry_name}</p>
              {!image && asset.role === 'embodiment' && (
                <p>Robot preview is included in the scene snapshot.</p>
              )}
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
export function SnapshotControls({
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
  );
}
export function SnapshotGallery({ snapshots, canonicalHash }: {
  snapshots: ReturnType<typeof useSnapshots>;
  canonicalHash: string | null;
}) {
  return (
    <section className="snapshot-section">
      <h2>Scene snapshots</h2>
      <p className="hint">
        Saved scene overviews. Use Render snapshots beside Assets to update the scene and thumbnails.
      </p>
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
                    !snapshotMatches(receipt, canonicalHash)
                      ? 'stale-label'
                      : 'muted'
                  }
                >
                  {!snapshotMatches(receipt, canonicalHash)
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
