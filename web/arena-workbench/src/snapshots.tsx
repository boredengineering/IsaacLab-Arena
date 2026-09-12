import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { Asset, CameraView, PreviewLookup, RenderOptions, SnapshotResult } from './editor-contracts';
import { snapshotHistorical, snapshotMatches, snapshotResult, type SnapshotReceipt } from './snapshot-model';
import { useEditorJob } from './editor-jobs';
import { useRuntime } from './runtime';
import { AUTOMATIC_PREVIEW_LIMIT, useAutomaticPreview } from './automatic-preview';

export const defaultRenderOptions: RenderOptions = { view: 'isometric', resolution: 1024, asset_views: {} };
function optionsIdentity(options?: RenderOptions) {
  if (!options || !options.asset_views || typeof options.asset_views !== 'object' || Array.isArray(options.asset_views)) return null;
  return JSON.stringify({ view: options.view, resolution: options.resolution,
    asset_views: Object.fromEntries(Object.entries(options.asset_views).sort()) });
}
export function CameraSelect({ label, value, onChange }: { label: string; value: CameraView; onChange: (view: CameraView) => void }) {
  return <label>{label}<select aria-label={label} value={value} onChange={(event) => onChange(event.target.value as CameraView)}>
    <option value="isometric">Isometric</option><option value="front">Front</option><option value="side">Side</option><option value="top">Top</option>
  </select></label>;
}
export function useSnapshots(canonicalHash: string | null, documentId: string, options = defaultRenderOptions) {
  const controller = useEditorJob('snapshots');
  const { api, session } = useRuntime();
  const optionKey = optionsIdentity(options)!;
  const last = useRef<{ receipt: SnapshotReceipt; options: string } | null>(null);
  const lookup = useQuery({
    queryKey: ['preview-catalogue', session?.session_id, canonicalHash, optionKey, controller.job?.id, controller.job?.status],
    queryFn: async () => {
      const query = new URLSearchParams({ view: options.view, resolution: String(options.resolution), asset_views: JSON.stringify(JSON.parse(optionKey).asset_views) });
      const result = await api.get<PreviewLookup>(`/editor/previews/${canonicalHash}?${query}`);
      if (result.canonical_hash !== canonicalHash || !['hit', 'historical', 'miss'].includes(result.status)
        || (result.status !== 'miss' && (!result.receipt || result.receipt.canonical_hash !== canonicalHash
          || !snapshotResult(result.receipt)
          || (result.status === 'historical') !== (result.receipt.freshness === 'unverified_assets')
          || optionsIdentity(result.receipt.options) !== optionKey))) {
        throw new Error('Preview catalogue identity mismatch; no cached images trusted.');
      }
      return result;
    },
    enabled: !!session && !!canonicalHash && /^[a-f0-9]{64}$/.test(canonicalHash),
    retry: false, gcTime: 0, staleTime: 0,
    refetchOnWindowFocus: true,
  });
  const receipt: SnapshotReceipt | undefined = !lookup.isFetching && !lookup.isError && lookup.data?.status !== 'miss' && lookup.data?.receipt
    ? { jobId: lookup.data.receipt.cache_key ?? canonicalHash!, documentId, canonicalHash, result: lookup.data.receipt }
    : undefined;
  useEffect(() => {
    if (receipt) last.current = { receipt, options: optionKey };
    else if (canonicalHash && !lookup.isFetching) last.current = null;
  }, [receipt, canonicalHash, lookup.isFetching, optionKey]);
  // Only a catalogue-checked image may remain while validation is pending;
  // historical receipts retain their explicit unverified-asset warning.
  // A miss/error/refetch never falls back to journal receipts or previous query data.
  const stale = !canonicalHash && last.current?.receipt.documentId === documentId && last.current.options === optionKey
    ? last.current.receipt : undefined;
  const history = receipt ? [receipt] : stale ? [stale] : [];
  return { controller, history, lookup, options, canonicalHash, optionKey };
}
export function SnapshotImage({ url, fullUrl = url, label }: { url: string; fullUrl?: string; label: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [fullLoading, setFullLoading] = useState(true);
  const [zoomed, setZoomed] = useState(false);
  useEffect(() => {
    setFailed(false);
    setLoading(true);
    setZoomed(false);
    dialog.current?.close();
  }, [url, fullUrl]);
  const trusted = (value: string) => /^\/api\/editor\/artifacts\/[a-zA-Z0-9_.-]+$/.test(value);
  if (!trusted(url) || !trusted(fullUrl))
    return <p className="error-text">Unsupported artifact URL.</p>;
  return (
    <>
      {failed ? (
        <div className="asset-placeholder image-error" role="alert">
          <span>Image unavailable. Retry after reconnecting, or render snapshots again.</span>
          <button aria-label={`Retry ${label}`} onClick={() => { setLoading(true); setFailed(false); }}>Retry image</button>
        </div>
      ) : (
        <button
          className="snapshot-image"
          aria-label={`Zoom ${label}`}
          onClick={() => { setFullLoading(true); setZoomed(true); dialog.current?.showModal(); }}
        >
          {loading && <span role="status">Loading {label}…</span>}
          <img src={url} alt={label} loading="lazy" decoding="async" onLoad={() => setLoading(false)} onError={() => setFailed(true)} />
        </button>
      )}
      <dialog className="zoom-dialog" aria-label={`Zoomed ${label}`} ref={dialog} onClose={() => setZoomed(false)}>
        <div className="section-heading">
          <h3>{label}</h3>
          <button onClick={() => { dialog.current?.close(); setZoomed(false); }}>Close image</button>
        </div>
        {zoomed && fullLoading && <p role="status">Loading full image…</p>}
        {zoomed && <img src={fullUrl} alt={`Zoomed ${label}`} decoding="async" onLoad={() => setFullLoading(false)} onError={() => {
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
  options,
  onCamera,
}: {
  assets: Asset[];
  receipt?: SnapshotReceipt;
  stale: boolean;
  options?: RenderOptions;
  onCamera?: (id: string, view: CameraView | '') => void;
}) {
  return (
    <>
    {receipt && <RenderDiagnostics result={receipt.result} />}
    <div className="asset-grid">
      {assets.map((asset) => {
        const image = receipt?.result.assets.find((a) => a.id === asset.id);
        return (
          <article className="asset-card" key={asset.id}>
            {image ? (
              <SnapshotImage url={image.variants?.thumbnail.url ?? image.url} fullUrl={image.variants?.full.url ?? image.url} label={`${asset.id} snapshot`} />
            ) : (
              <div className="asset-placeholder">
                {asset.role === 'embodiment' ? 'Scene preview only' : 'No saved preview'}
              </div>
            )}
            <div className="asset-caption">
              <span className="asset-role">{asset.role}</span>
              <strong>{asset.id}</strong>
              {onCamera && <label>Asset camera<select aria-label={`Camera for ${asset.id}`} value={options?.asset_views[asset.id] ?? ''} onChange={(event) => onCamera(asset.id, event.target.value as CameraView | '')}>
                <option value="">Scene default</option><option value="isometric">Isometric</option><option value="front">Front</option><option value="side">Side</option><option value="top">Top</option>
              </select></label>}
              <p>{asset.registry_name}</p>
              {receipt?.result.errors?.filter((error) => error.id === asset.id).map((error, index) => <p className="error-text" key={index}>{error.stage} · {error.code}: {error.message}</p>)}
              {!image && asset.role === 'embodiment' && (
                <p>Robot preview is included in the scene snapshot.</p>
              )}
              {image && stale && <p className="stale-label">Stale · draft changed</p>}
              {asset.parent_id && <small>Parent: {asset.parent_id}</small>}
              {asset.prim_path && <code>{asset.prim_path}</code>}
              {image?.dimensions_m && (
                <details className="dimension-metadata">
                  <summary><small title={image.dimensions_m.join(' × ')}>Dimensions (m): {image.dimensions_m.map((value) => Number(value.toFixed(3))).join(' × ')}</small></summary>
                  <pre>{JSON.stringify({ dimensions_m: image.dimensions_m, variants: image.variants }, null, 2)}</pre>
                </details>
              )}
            </div>
          </article>
        );
      })}
    </div>
    </>
  );
}
function RenderDiagnostics({ result }: { result: SnapshotResult }) {
  return <div className="render-diagnostics">
    {result.freshness === 'unverified_assets' && <p className="warning-text">Historical preview · asset freshness unverified</p>}
    {result.partial && <p className="warning-text">Partial preview · some artifacts failed</p>}
    {result.warnings.map((warning, index) => <p className="warning-text" key={index}>{warning}</p>)}
    {!!result.errors?.length && <details><summary>Render errors ({result.errors.length})</summary>
      {result.errors.map((error, index) => <p key={index}>{error.id} · {error.stage} · {error.code}: {error.message}</p>)}
    </details>}
    {result.timings && <details><summary>Renderer timings</summary>
      {Object.entries(result.timings).map(([stage, value]) => <p key={stage} title={String(value)}>{stage}: {Number(value.toFixed(3))}</p>)}
    </details>}
    <details><summary>Precise render metadata</summary><pre>{JSON.stringify(result, null, 2)}</pre></details>
  </div>;
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
  const { controller } = snapshots;
  const request = { yaml_text: draft, options: { ...snapshots.options, asset_views: { ...snapshots.options.asset_views } },
    ...(documentId ? { document_id: documentId } : {}) };
  const blocked = !!(controller.retained && !controller.job) || !!controller.error
    || !!controller.cancel.isPending || ['failed', 'indeterminate', 'cancel_requested', 'cancelled'].includes(controller.job?.status ?? '');
  const automatic = useAutomaticPreview({
    identity: snapshots.canonicalHash ? `${documentId}:${snapshots.canonicalHash}:${snapshots.optionKey}` : null,
    ready: enabled && !!snapshots.canonicalHash && !snapshots.lookup.isFetching && !snapshots.lookup.isError && snapshots.lookup.data?.status === 'miss',
    busy: controller.busy, blocked, request, submit: controller.submit.mutateAsync,
  });
  return (
        <div className="snapshot-controls">
        <button
          disabled={!enabled || controller.busy || automatic.inFlight}
          onClick={() => { automatic.setEnabled(false); controller.submit.mutate(request); }}
        >
          {snapshots.controller.submit.isPending
            ? 'Submitting render…'
            : snapshots.controller.retained && !snapshots.controller.job
              ? 'Retry snapshot request'
              : 'Render snapshots'}
        </button>
        <label className="automatic-consent"><input type="checkbox" checked={automatic.enabled}
          disabled={!automatic.enabled && (!enabled || blocked || controller.busy)}
          onChange={(event) => automatic.setEnabled(event.target.checked)} />Automatic previews (GPU jobs)</label>
        <p className="hint">{automatic.count} / {AUTOMATIC_PREVIEW_LIMIT} automatic jobs used this enable. Stable validated changes only; 1.5 s debounce, ≥10 s between jobs, one in flight. Off after navigation/reload. Manual rendering turns this off.</p>
        {automatic.enabled && (automatic.halted || blocked) && <p className="warning-text">Automatic previews paused. Resolve the job explicitly; no automatic retry.</p>}
        {automatic.enabled && automatic.count >= AUTOMATIC_PREVIEW_LIMIT && <p className="warning-text">Automatic preview budget exhausted. Disable and explicitly re-enable to authorize another budget.</p>}
        </div>
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
          No saved scene preview for these options. Render explicitly, or opt in to bounded automatic previews for subsequent validated changes.
        </div>
      ) : (
        <div className="scene-gallery">
          {snapshots.history.map((receipt) => (
            <figure key={receipt.jobId}>
              {receipt.result.scene ? (
                <SnapshotImage
                  url={receipt.result.scene.variants?.thumbnail.url ?? receipt.result.scene.url}
                  fullUrl={receipt.result.scene.variants?.full.url ?? receipt.result.scene.url}
                  label={`scene snapshot ${receipt.jobId}`}
                />
              ) : (
                <p className="empty-state">No scene image returned.</p>
              )}
              <figcaption>
                <strong>Scene overview</strong>
                <RenderDiagnostics result={receipt.result} />
                <p
                  className={
                    !snapshotMatches(receipt, canonicalHash)
                      ? 'stale-label'
                      : 'muted'
                  }
                >
                  {!snapshotMatches(receipt, canonicalHash)
                    ? 'Stale · draft changed since this render'
                    : snapshotHistorical(receipt) ? 'Saved pixels only · render explicitly to update' : 'Matches current draft'}
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
