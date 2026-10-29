import React, { useEffect, useId, useRef, useState } from 'react';

export interface VisualizerFrame {
  id: string;
  kind: 'asset' | 'scene';
  label: string;
  camera: 'isometric' | 'front' | 'side' | 'top' | 'recorded';
  width: number;
  height: number;
  url: string;
  sha256: string;
  sourceLabel: string;
  captureId: string;
}

export interface AssetSceneVisualizerProps {
  frames: readonly VisualizerFrame[];
  draft: string;
  sourceId: string;
}

const cameras: VisualizerFrame['camera'][] = ['isometric', 'front', 'side', 'top', 'recorded'];
const tabs = ['Assets', 'Scene', 'Live RTX exploration'];
const frameKey = (frame: VisualizerFrame) => JSON.stringify([frame.id, frame.captureId, frame.camera, frame.sha256]);
type RenderPlan = { sourceId: string; draft: string; options: { camera: string; resolution: number }; localOnly: true; submitted: false };
type Review<T> = { payload: T; stale: boolean };
type LivePlan = RenderPlan & { candidateProfile: string; intent: string; requirements: readonly string[] };
const liveRequirements = [
  'Verify ovrtx API, runtime compatibility, licensing and supported NVIDIA GPU/driver in a separately authorized rendering worker.',
  'Design authenticated transport, origin checks, resource limits and explicit disconnect before any connection.',
  'Authorize camera input separately from view-only output; verify picking against stable scene identities.',
  'Keep edit proposals separate from draft application and require explicit review; no physics or robot control permission.',
];

function SavedImage({ frame }: { frame: VisualizerFrame }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const zoomButton = useRef<HTMLButtonElement>(null);
  const [failed, setFailed] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  useEffect(() => {
    const node = dialog.current;
    if (zoomed) node?.showModal();
    return () => { if (node?.open) node.close(); };
  }, [zoomed]);
  const close = () => { if (dialog.current?.open) dialog.current.close(); setZoomed(false); zoomButton.current?.focus(); };
  const fail = () => { close(); setFailed(true); };
  // Only embedded raster pixels / parent-owned local blobs: no HTTP or API image loads.
  if (!/^(data:image\/(png|jpeg|webp|gif|avif);base64,[a-zA-Z0-9+/=\r\n]+$|blob:)/.test(frame.url)) {
    return <p className="preview-visualizer-error" role="alert">Image unavailable — supply an embedded raster image or local blob URL.</p>;
  }
  const label = `${frame.label} · ${frame.camera}`;
  return <>
    {failed ? <div className="preview-empty preview-visualizer-error" role="alert">Saved image could not be loaded. No new render was requested.<button type="button" onClick={() => setFailed(false)}>Retry saved image</button></div>
      : <button ref={zoomButton} type="button" className="preview-visualizer-image" aria-label="Zoom historical image" onClick={() => setZoomed(true)}><img src={frame.url} alt={`Historical ${label}`} width={frame.width} height={frame.height} onError={fail} /></button>}
    {zoomed && <dialog ref={dialog} className="preview-visualizer-zoom" aria-label="Historical image zoom" onCancel={event => { event.preventDefault(); close(); }} onClose={close}>
      <h3>Historical {label}</h3><p>Saved pixels only — not a current-draft render.</p><button type="button" autoFocus onClick={close}>Close image</button>
      <img src={frame.url} alt={`Zoomed historical ${label}`} onError={fail} />
    </dialog>}
  </>;
}

/**
 * Offline saved pixels and local planning only; no runtime/provider dependencies.
 * Within each kind, label groups a subject's camera/capture records; use distinct
 * labels for distinct subjects. Supply immutable records and embedded raster data
 * or parent-owned blob URLs (HTTP, API and SVG URLs are deliberately refused).
 * sha256 is supplied provenance, not a digest verified by this component.
 */
export function AssetSceneVisualizer({ frames, draft, sourceId }: AssetSceneVisualizerProps) {
  const id = useId();
  const [tab, setTab] = useState('Assets');
  const [plannedCamera, setPlannedCamera] = useState('isometric');
  const [resolution, setResolution] = useState(1024);
  const [renderConsent, setRenderConsent] = useState(false);
  const [renderReview, setRenderReview] = useState<Review<RenderPlan> | null>(null);
  const [intent, setIntent] = useState('view-only');
  const [liveConsent, setLiveConsent] = useState(false);
  const [liveReview, setLiveReview] = useState<Review<LivePlan> | null>(null);
  const binding = JSON.stringify([sourceId, draft, plannedCamera, resolution, intent]);
  const [observedBinding, setObservedBinding] = useState(binding);
  // Latch changes before committing controls. A→B→A never revives consent or a review.
  if (observedBinding !== binding) {
    setObservedBinding(binding);
    setRenderConsent(false);
    setRenderReview(previous => previous ? { ...previous, stale: true } : null);
    setLiveConsent(false);
    setLiveReview(previous => previous ? { ...previous, stale: true } : null);
  }
  const [subject, setSubject] = useState({ asset: '', scene: '' });
  const [capture, setCapture] = useState<{ scope: string; key: string } | null>(null);
  const [camera, setCamera] = useState<VisualizerFrame['camera']>(frames[0]?.camera ?? 'recorded');
  const kind = tab === 'Scene' ? 'scene' : 'asset';
  const subjects = [...new Set(frames.filter(frame => frame.kind === kind).map(frame => frame.label))];
  const selectedSubject = subject[kind] || subjects[0] || '';
  const captureScope = JSON.stringify([kind, selectedSubject, camera]);
  const matches = frames.filter(item => item.kind === kind && item.label === selectedSubject && item.camera === camera);
  const frame = capture?.scope === captureScope ? matches.find(item => frameKey(item) === capture.key) : matches[0];
  const live = tab === 'Live RTX exploration';
  return <section className="preview-visualizer" aria-label="Asset and scene visualizer">
    <div className="preview-tabs" role="tablist" aria-label="Visualizer views">
      {tabs.map((value, index) => <button type="button" role="tab" id={`${id}-tab-${index}`} aria-controls={`${id}-panel`} aria-selected={tab === value} tabIndex={tab === value ? 0 : -1} key={value} onClick={() => setTab(value)} onKeyDown={event => {
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : null;
        if (next === null) return;
        event.preventDefault(); setTab(tabs[next]);
        event.currentTarget.parentElement?.querySelectorAll('button')[next]?.focus();
      }}>{value}</button>)}
    </div>
    <div className="preview-visualizer-tabpanel" role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-tab-${tabs.indexOf(tab)}`}>
    {live ? <section className="preview-panel preview-visualizer-live" aria-label="Live RTX requirements exploration">
      <h2>ovrtx — candidate profile, not integrated</h2>
      <p>Candidate stack: ovstage scene state → ovrtx rendering → ovstream WebRTC → dashboard. NVIDIA provides a browser composition example; this preview does not connect it.</p>
      <p><a href="https://github.com/NVIDIA-Omniverse/ovstream/tree/main/examples/python/ovrtx_stream" target="_blank" rel="noopener noreferrer">Official NVIDIA ovrtx + ovstream example</a></p>
      <p className="preview-tag">Not live — no 3D input is streamed. No connection, rendered stream or interactive scene is available in this preview.</p>
      <p>Rendering is not physics. Camera and picking intentions do not authorize simulation steps, scene edits or robot control.</p>
      <label className="preview-field">Interaction intent<select aria-label="Interaction intent" value={intent} onChange={event => setIntent(event.target.value)}>
        <option value="view-only">View-only</option><option value="camera">Camera</option><option value="picking">Picking</option><option value="edit-proposal">Edit-proposal</option>
      </select></label>
      <ul className="preview-visualizer-requirements">{liveRequirements.map(requirement => <li key={requirement}>{requirement}</li>)}</ul>
      <label className="preview-visualizer-consent"><input type="checkbox" checked={liveConsent} disabled={!!liveReview} onChange={event => setLiveConsent(event.target.checked)} />I understand this is requirements review, not connection consent</label>
      <button type="button" disabled={!liveConsent || !!liveReview} onClick={() => setLiveReview({ stale: false, payload: { sourceId, draft, options: { camera: plannedCamera, resolution }, candidateProfile: 'ovrtx (evaluation only)', intent, requirements: [...liveRequirements], localOnly: true, submitted: false } })}>Review live requirements locally</button>
      <button type="button" disabled>Connect</button><p className="preview-muted">Connect is unavailable: no transport or runtime integration exists here.</p>
      {liveReview && <section className="preview-candidate preview-visualizer-review" aria-label="Frozen live requirements review"><h3>Frozen live requirements review</h3>
        <p>Requirements only — no connection or capability validation. Clear explicitly before freezing another review.</p>
        {liveReview.stale && <p className="preview-visualizer-stale" role="status">Live requirements review is stale — source, draft or planning options changed. Frozen content is unchanged.</p>}
        <pre data-testid="visualizer-live-review">{JSON.stringify(liveReview.payload, null, 2)}</pre>
        <button type="button" onClick={() => { setLiveReview(null); setLiveConsent(false); }}>Clear live requirements review</button>
      </section>}
    </section> : <section className="preview-panel preview-visualizer-gallery" aria-label="Historical saved images">
      <h2>Historical saved images</h2>
      <p>Historical images — not verified against the current draft. Selecting a camera never renders or relabels saved pixels.</p>
      <label className="preview-field">Saved subject<select aria-label="Saved subject" value={selectedSubject} onChange={event => setSubject({ ...subject, [kind]: event.target.value })}>{selectedSubject && !subjects.includes(selectedSubject) && <option value={selectedSubject} disabled>{selectedSubject} (missing)</option>}{subjects.map(value => <option key={value}>{value}</option>)}</select></label>
      <label className="preview-field">Saved camera<select aria-label="Saved camera" value={camera} onChange={event => setCamera(event.target.value as VisualizerFrame['camera'])}>{cameras.map(value => <option key={value}>{value}</option>)}</select></label>
      {matches.length > 1 && <label className="preview-field">Saved capture<select aria-label="Saved capture" value={frame ? frameKey(frame) : ''} onChange={event => setCapture({ scope: captureScope, key: event.target.value })}>{!frame && <option value="" disabled>Selected capture missing</option>}{matches.map(item => <option key={frameKey(item)} value={frameKey(item)}>{item.captureId} · {item.id} · {item.sourceLabel}</option>)}</select></label>}
      {frame ? <figure className="preview-visualizer-frame">
        <SavedImage key={frameKey(frame) + frame.url} frame={frame} />
        <figcaption>Historical {frame.label} · {frame.camera}</figcaption>
        <details><summary>Saved image metadata</summary><pre data-testid="visualizer-frame-metadata">{JSON.stringify({ id: frame.id, kind: frame.kind, label: frame.label, camera: frame.camera, width: frame.width, height: frame.height, sha256: frame.sha256, sourceLabel: frame.sourceLabel, captureId: frame.captureId }, null, 2)}</pre></details>
      </figure> : <div className="preview-empty preview-visualizer-missing" role="status">{matches.length ? <>Selected historical capture is no longer supplied.<button type="button" onClick={() => setCapture(null)}>Use first available saved capture</button></> : subjects.length ? `No saved ${camera} view for ${selectedSubject}.` : `No historical ${kind} images supplied.`}</div>}
    </section>}
    </div>
    <section className="preview-panel preview-visualizer-planning" aria-label="Local render planning">
      <h2>Render planning — local only</h2>
      <p>No GPU action, validation or render submission. Planning controls do not change historical images.</p>
      <p className="preview-muted">Current source: <code>{sourceId || 'No source selected'}</code></p>
      <label className="preview-field">Planned camera<select aria-label="Planned camera" value={plannedCamera} onChange={event => setPlannedCamera(event.target.value)}>{cameras.filter(value => value !== 'recorded').map(value => <option key={value}>{value}</option>)}</select></label>
      <label className="preview-field">Planned resolution<select aria-label="Planned resolution" value={resolution} onChange={event => setResolution(Number(event.target.value))}>{[512, 1024, 2048].map(value => <option key={value} value={value}>{value} × {value}</option>)}</select></label>
      {!live && <><label className="preview-visualizer-consent"><input type="checkbox" checked={renderConsent} disabled={!!renderReview} onChange={event => setRenderConsent(event.target.checked)} />I understand this render plan is local only</label>
      <button type="button" disabled={!renderConsent || !!renderReview} onClick={() => setRenderReview({ stale: false, payload: { sourceId, draft, options: { camera: plannedCamera, resolution }, localOnly: true, submitted: false } })}>Review render request locally</button>
      {renderReview && <section className="preview-candidate preview-visualizer-review" aria-label="Frozen render request review"><h3>Frozen render request review</h3>
        <p>Not submitted. Clear this review explicitly before freezing another.</p>
        {renderReview.stale && <p className="preview-visualizer-stale" role="status">Render review is stale — source, draft or planning options changed. Frozen content is unchanged.</p>}
        <pre data-testid="visualizer-render-review">{JSON.stringify(renderReview.payload, null, 2)}</pre>
        <button type="button" onClick={() => { setRenderReview(null); setRenderConsent(false); }}>Clear render review</button>
      </section>}</>}
    </section>
  </section>;
}
