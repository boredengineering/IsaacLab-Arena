import { useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import type { PreviewSelection } from './types';

interface Props {
 selection: PreviewSelection | null;
 draft: string;
 onDraft: (draft: string) => void;
 expanded: boolean;
 onExpandViewport: () => void;
 onReturnToEditor: () => void;
 onLoadExample: () => void;
 children: ReactNode;
}
type Vector = [number, number, number];
type Asset = { id: string; registry: string; parent: string | null; pose: { position: Vector; rotationDegrees: Vector }; scale: Vector };
type Document = { previewSchema: 'inspect-correct/v1'; synthetic: true; assets: Asset[] };
type Finding = { path: string; message: string; key?: string; occurrence?: number; total?: number };
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const keys = (value: Record<string, unknown>, allowed: string[]) => Object.keys(value).length === allowed.length && allowed.every(key => Object.hasOwn(value, key));
const vector = (value: unknown, scale = false): value is Vector => Array.isArray(value) && value.length === 3 && value.every(n => typeof n === 'number' && Number.isFinite(n) && (scale ? n > 0 && n <= 10000 : Math.abs(n) <= 1000000));
function inspectDraft(raw: string): { document: Document | null; findings: Finding[] } {
 const fail = (message: string) => ({ document: null, findings: [{ path: 'specification', message }] });
 if (raw.length > 65536) return fail('Local inspection has a 65,536 character limit. Shorten a copy; your raw draft is preserved.');
 if (!raw.trim()) return fail('No authored assets yet. Load the synthetic inspection example or enter the declared preview format.');
 let value: unknown;
 try { value = JSON.parse(raw); } catch { return fail('Unsupported inspector: only JSON text (a YAML subset) is supported. Use quoted keys and remove comments/trailing commas. Other YAML remains unchanged.'); }
 // JSON.parse accepts duplicate keys; refuse that ambiguity before exposing properties.
 const scopes: (Set<string> | null)[] = [];
 const tokens = [...raw.matchAll(/"(?:\\.|[^"\\])*"|[{}\[\]:,]/g)];
 for (let i = 0; i < tokens.length; i++) {
  const token = tokens[i][0];
  if (token === '{' || token === '[') scopes.push(token === '{' ? new Set() : null);
  else if (token === '}' || token === ']') scopes.pop();
  else if (token.startsWith('"') && tokens[i + 1]?.[0] === ':') {
   const key = JSON.parse(token) as string; const scope = scopes[scopes.length - 1];
   if (scope?.has(key)) return fail('Duplicate JSON key: remove repeated keys before local inspection. Raw draft preserved.');
   scope?.add(key);
  }
 }
 if (!record(value) || value.previewSchema !== 'inspect-correct/v1' || value.synthetic !== true) return fail('Unsupported inspector: declare previewSchema "inspect-correct/v1" and synthetic true. This is not Arena schema.');
 if (!keys(value, ['previewSchema', 'synthetic', 'assets'])) return fail('Unsupported fields: this narrow preview accepts only previewSchema, synthetic and assets.');
 if (!Array.isArray(value.assets) || value.assets.length > 64) return fail('assets must be an array of at most 64 authored assets.');
 const findings: Finding[] = [];
 const assets = value.assets;
 assets.forEach((a: unknown, i: number) => {
  const add = (field: string, message: string) => findings.push({ path: `assets[${i}].${field}`, message, key: field, occurrence: i, total: assets.length });
  if (!record(a) || !keys(a, ['id', 'registry', 'parent', 'pose', 'scale'])) { add('id', 'Use exactly id, registry, parent, pose and scale on each asset.'); return; }
  if (typeof a.id !== 'string' || !/^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/.test(a.id)) add('id', 'Use a unique authored ID: letter followed by up to 63 letters, digits, underscores or hyphens.');
  if (typeof a.registry !== 'string' || !/^preview:[a-zA-Z0-9_-]{1,64}$/.test(a.registry)) add('registry', 'Use a preview-only registry label, e.g. preview:cube.');
  if (a.parent !== null && (typeof a.parent !== 'string' || !assets.some(b => record(b) && b.id === a.parent))) add('parent', 'Use null or an existing authored asset ID.');
  if (!record(a.pose) || !keys(a.pose, ['position', 'rotationDegrees']) || !vector(a.pose.position) || !vector(a.pose.rotationDegrees)) add('pose', 'Use position and rotationDegrees arrays of three finite numbers, each within ±1,000,000.');
  if (!vector(a.scale, true)) add('scale', 'Use three positive finite scale values, each at most 10,000.');
  if (assets.some((b, j) => j !== i && record(b) && b.id === a.id)) add('id', 'Duplicate authored ID. Give each asset a unique ID.');
  const visited = new Set<unknown>([a.id]); let parent = a.parent;
  for (let step = 0; parent !== null && step <= assets.length; step++) {
   if (visited.has(parent)) { add('parent', 'Parent cycle: use an acyclic authored hierarchy.'); break; }
   visited.add(parent); parent = assets.find(b => record(b) && b.id === parent)?.parent ?? null;
  }
 });
 return { document: findings.length ? null : value as Document, findings };
}

export function InspectCorrectWorkspace({ selection, draft, onDraft, expanded, onExpandViewport, onReturnToEditor, onLoadExample, children }: Props) {
 const editor = useRef<HTMLTextAreaElement>(null);
 const [specificationHidden, setSpecificationHidden] = useState(false);
 const [inspectorHidden, setInspectorHidden] = useState(false);
 const [specificationWidth, setSpecificationWidth] = useState(30);
 const inspection = useMemo(() => inspectDraft(draft), [draft]);
 const [assetId, setAssetId] = useState(() => inspection.document?.assets[0]?.id ?? '');
 const asset = inspection.document?.assets.find(item => item.id === assetId);
 // A monotonic render-time fence prevents a retained review reviving on A→B→A.
 // Include every source option, including original bytes, not just the version ID.
 const source = JSON.stringify(selection);
 const [binding, setBinding] = useState({ source, draft, epoch: 0, sourceEpoch: 0 });
 let current = binding;
 if (binding.source !== source || binding.draft !== draft) {
  current = { source, draft, epoch: binding.epoch + 1, sourceEpoch: binding.sourceEpoch + (binding.source !== source ? 1 : 0) };
  setBinding(current);
 }
 const [field, setField] = useState<'position' | 'rotationDegrees'>('position');
 const [axis, setAxis] = useState(0);
 const [value, setValue] = useState('');
 const [optionsEpoch, setOptionsEpoch] = useState(0);
 const [proposal, setProposal] = useState<Readonly<{ before: string; after: string; source: string; sourceLabel: string; epoch: number; optionsEpoch: number; diff: string }> | null>(null);
 const [consent, setConsent] = useState(false);
 const [applied, setApplied] = useState(false);
 if (binding.source !== source || (assetId !== '' && !asset)) {
  // Retire editing intent, but retain the frozen review as visibly stale evidence.
  setAssetId(''); setField('position'); setAxis(0); setValue('');
  setOptionsEpoch(n => n + 1); setConsent(false);
 }
 const freshProposal = !!proposal && !applied && proposal.epoch === current.epoch && proposal.optionsEpoch === optionsEpoch && proposal.source === source && proposal.before === draft;
 const numeric = Number(value);
 const canPropose = !!asset && !!inspection.document && value.trim() !== '' && Number.isFinite(numeric) && Math.abs(numeric) <= 1000000 && asset.pose[field][axis] !== numeric;
 function changeOptions(action: () => void) { action(); setOptionsEpoch(n => n + 1); setConsent(false); }
 function reviewPose() {
  if (!canPropose || !inspection.document || !asset) return;
  const index = inspection.document.assets.indexOf(asset);
  const next: Document = JSON.parse(draft);
  next.assets[index].pose[field][axis] = numeric;
  const path = `assets[${index}].pose.${field}[${axis}]`;
  setProposal(Object.freeze({ before: draft, after: JSON.stringify(next, null, 2) + '\n', source,
   sourceLabel: selection ? `${selection.versionId} · ${selection.source}` : 'Unbound local draft', epoch: current.epoch, optionsEpoch,
   diff: `- ${path}: ${asset.pose[field][axis]}\n+ ${path}: ${numeric}` }));
  setConsent(false); setApplied(false);
 }
 function applyPose() {
  if (!freshProposal || !proposal || !consent) return;
  setApplied(true); setConsent(false); onDraft(proposal.after);
 }
 const [downloadError, setDownloadError] = useState('');
 type Copy = Readonly<{ raw: string; source: string; sourceEpoch: number; label: string }>;
 const [copy, setCopy] = useState<Copy | null>(null);
 const [recovery, setRecovery] = useState<Readonly<{ copy: Copy; epoch: number; before: string }> | null>(null);
 const [restoreConsent, setRestoreConsent] = useState(false);
 const sameCopySource = !!copy && copy.source === source && copy.sourceEpoch === current.sourceEpoch;
 const freshRecovery = sameCopySource && !!recovery && recovery.copy === copy && recovery.epoch === current.epoch && recovery.before === draft;
 function keepCopy() {
  if (copy) return;
  setCopy(Object.freeze({ raw: draft, source, sourceEpoch: current.sourceEpoch, label: selection?.versionId ?? 'Unbound local draft' }));
 }
 function reviewRecovery() {
  if (!copy || !sameCopySource) return;
  setRecovery(Object.freeze({ copy, epoch: current.epoch, before: draft })); setRestoreConsent(false);
 }
 function discardCopy() { setCopy(null); setRecovery(null); setRestoreConsent(false); }
 function restoreCopy() {
  if (!recovery || !freshRecovery || !restoreConsent) return;
  const raw = recovery.copy.raw; discardCopy(); onDraft(raw);
 }
 function downloadDraft() {
  setDownloadError(''); let url: string | undefined;
  try {
   url = URL.createObjectURL(new Blob([draft], { type: 'application/yaml;charset=utf-8' }));
   const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'inspection-draft.yaml';
   document.body.append(anchor);
   try { anchor.click(); } finally { anchor.remove(); }
  } catch { setDownloadError('Local download unavailable. Select and copy the raw draft manually; it has not been changed.'); }
  finally { if (url) URL.revokeObjectURL(url); }
 }
 function focusFinding(finding: Finding) {
  const field = editor.current; if (!field) return;
  field.focus();
  const matches = finding.key ? [...draft.matchAll(new RegExp(`"${finding.key}"\\s*:`, 'g'))] : [];
  // Missing/escaped/additional keys make ordinal field mapping uncertain: focus
  // the specification instead of pointing at a different authored asset.
  const match = matches.length === finding.total ? matches[finding.occurrence ?? 0] : undefined;
  field.setSelectionRange(match?.index ?? 0, match ? match.index + match[0].length : draft.length);
 }

 return <section className={`inspect-workspace${expanded ? ' is-expanded' : ''}${specificationHidden ? ' specification-collapsed' : ''}${inspectorHidden ? ' inspector-collapsed' : ''}`} style={{ '--inspect-spec-width': `${specificationWidth}%` } as CSSProperties} aria-label="Inspect and correct workspace">
  <header className="inspect-workspace-header"><h2>Inspect & correct</h2><p>Offline authored specification · no simulator connection</p>
   <button type="button" onClick={() => setSpecificationHidden(hidden => !hidden)}>{specificationHidden ? 'Show specification' : 'Hide specification'}</button>
   <button type="button" onClick={() => setInspectorHidden(hidden => !hidden)}>{inspectorHidden ? 'Show inspector' : 'Hide inspector'}</button>
   <label className="inspect-spec-width">Specification width<input type="range" min={25} max={40} step={1} value={specificationWidth} aria-valuetext={`${specificationWidth} percent`} disabled={expanded || specificationHidden} onChange={event => setSpecificationWidth(Number(event.target.value))} /></label>
  </header>
  <div className="inspect-workspace-grid">
   <section className="inspect-specification" hidden={expanded || specificationHidden} aria-label="Specification">
    <h3>Specification</h3><p>{selection ? `${selection.familyName} · version ${selection.version}` : 'No source selected. Start with a synthetic inspection example or edit a local draft.'}</p>
    {!selection && <button type="button" onClick={onLoadExample}>Load inspection example</button>}
    <label>Draft YAML<textarea aria-label="Draft YAML" ref={editor} value={draft} onChange={event => onDraft(event.target.value)} spellCheck={false} /></label>
    <div className="inspect-draft-actions"><button type="button" onClick={downloadDraft}>Download raw draft</button><button type="button" disabled={!!copy} onClick={keepCopy}>Keep recovery copy</button></div>
    <p>Raw local YAML download only — no flattening or schema-success claim. Recovery stays in this mounted workspace’s memory; closing or reloading loses it. No browser storage.</p>
    {downloadError && <p role="alert">{downloadError}</p>}
    {copy && <section className="inspect-recovery" aria-label="Memory recovery copy"><h4>Memory recovery copy</h4><p>{copy.label} · {copy.raw.length} characters</p>
     <p>{sameCopySource ? 'Copy retained. Review before replacing the current draft.' : 'Source changed — this recovery copy is blocked, even after returning to the old source. Discard explicitly.'}</p>
     <button type="button" disabled={!sameCopySource} onClick={reviewRecovery}>Review recovery copy</button><button type="button" onClick={discardCopy}>Discard recovery copy</button>
     {recovery && <section className="inspect-recovery-review" aria-label="Frozen recovery review"><h4>Frozen recovery review</h4><pre>{recovery.copy.raw}</pre>
      <p>Replaces the entire current draft ({recovery.before.length} characters) with this exact raw copy. No parsing or repair.</p>
      {!freshRecovery && <p role="status">Stale recovery review — source or draft changed. A new review is required; a changed source cannot be restored.</p>}
      <label><input type="checkbox" checked={freshRecovery && restoreConsent} disabled={!freshRecovery} onChange={event => setRestoreConsent(event.target.checked)} />I consent to replace the current draft with this recovery copy</label>
      <button type="button" disabled={!freshRecovery || !restoreConsent} onClick={restoreCopy}>Restore reviewed recovery copy</button>
     </section>}
    </section>}
    <section className="inspect-validation" aria-label="Local validation" aria-live="polite">
     <p>JSON-subset preview checks only: structure, numeric bounds and authored references. No Arena schema, registry resolution, physics, collision or renderer validation.</p>
     {inspection.document ? <p>Local preview checks passed — not runtime validation.</p> : <ul>{inspection.findings.map(finding => <li key={`${finding.path}:${finding.message}`}><p>{finding.message}</p><button type="button" onClick={() => focusFinding(finding)}>Inspect finding: {finding.path}</button></li>)}</ul>}
    </section>
   </section>
   <section className="inspect-viewport" aria-label="Viewport">
    <header><h3>Viewport</h3><button type="button" onClick={expanded ? onReturnToEditor : onExpandViewport}>{expanded ? 'Return to editor' : 'Expand viewport'}</button></header>
    <div className="inspect-viewport-content">{children}</div>
   </section>
   <aside className="inspect-inspector" hidden={expanded || inspectorHidden} aria-label="Authored asset inspector">
    <h3>Inspector</h3><p className="inspect-mapping-unavailable">Renderer mapping unavailable — authored IDs and preview registry labels do not identify runtime prims or visible pixels. Viewport selection/focus is unavailable.</p>
    {!inspection.document ? <p>Authored properties unavailable until this draft matches the declared preview format.</p> : <>
     <ul className="inspect-asset-list" aria-label="Authored assets">{inspection.document.assets.map(item => <li key={item.id}><button type="button" aria-pressed={item.id === asset?.id} onClick={() => changeOptions(() => setAssetId(item.id))}>Select {item.id}</button></li>)}</ul>
     {!asset && <p>{inspection.document.assets.length ? 'No authored asset selected. Select an asset to inspect or propose a pose change.' : 'No authored assets in this document.'}</p>}
     {asset && <section className="inspect-properties" aria-label="Read-only authored properties"><h4>{asset.id}</h4><dl>
      <dt>Authored ID</dt><dd>{asset.id}</dd><dt>Preview registry</dt><dd>{asset.registry}</dd>
      <dt>Authored parent</dt><dd>{asset.parent ?? 'None (authored root)'}</dd>
      <dt>Position (parent-local, preview units)</dt><dd>{asset.pose.position.join(', ')}</dd>
      <dt>Rotation (degrees, authored XYZ)</dt><dd>{asset.pose.rotationDegrees.join(', ')}</dd>
      <dt>Scale</dt><dd>{asset.scale.join(', ')}</dd>
     </dl></section>}
     {asset && <fieldset className="inspect-pose-controls"><legend>Propose authored pose change</legend>
      <label>Pose field<select aria-label="Pose field" value={field} onChange={event => changeOptions(() => setField(event.target.value as typeof field))}><option value="position">Position</option><option value="rotationDegrees">Rotation (degrees)</option></select></label>
      <label>Pose axis<select aria-label="Pose axis" value={axis} onChange={event => changeOptions(() => setAxis(Number(event.target.value)))}>{['X', 'Y', 'Z'].map((name, i) => <option key={name} value={i}>{name}</option>)}</select></label>
      <label>Proposed value<input type="number" step="any" min={-1000000} max={1000000} value={value} onChange={event => changeOptions(() => setValue(event.target.value))} /></label>
      <p>Enter a different finite value within ±1,000,000. Only the reviewed authored coordinate changes; no renderer mapping or physics check.</p>
      <button type="button" disabled={!canPropose} onClick={reviewPose}>Review pose change</button>
     </fieldset>}
    </>}
    {proposal && <section className="inspect-pose-review" aria-label="Frozen pose review">
     <h4>Frozen pose review</h4><p>{proposal.sourceLabel}</p><pre>{proposal.diff}</pre>
     <p>Apply replaces the full draft with formatted JSON (YAML subset). Whitespace will be normalized; this is not a flattened Arena export.</p>
     <p role="status">{applied ? 'Applied locally. This review cannot be applied again.' : freshProposal ? 'Review is bound to the exact current source, draft and edit options.' : 'Stale review — source, draft or edit options changed. Create a new review; returning to old values does not revive consent.'}</p>
     <label><input type="checkbox" checked={freshProposal && consent} disabled={!freshProposal} onChange={event => setConsent(event.target.checked)} />I consent to replace the draft with this reviewed pose change</label>
     <button type="button" disabled={!freshProposal || !consent} onClick={applyPose}>Apply reviewed pose change</button>
     <button type="button" onClick={() => { setProposal(null); setConsent(false); setApplied(false); }}>Clear pose review</button>
    </section>}
   </aside>
  </div>
 </section>;
}
