import { useEffect, useState } from 'react';
import type { PreviewSelection } from './types';
export interface EnvironmentPanelProps {
 selection: PreviewSelection | null;
 draft: string;
 prompt: string;
 onDraft: (value: string) => void;
 onPrompt: (value: string) => void;
 onApplyExample?: (yaml: string, detached: boolean) => void;
 onComposerDirty?: (dirty: boolean) => void;
 onOpenVisualizer?: () => void;
 hideDraftWorkspace?: boolean;
}
const A2_EXAMPLE = `# Design example only — not model output or a validated scene.
env_name: example-a2-banana-to-plate
embodiment: droid_abs_joint_pos
background: maple_table_robolab
objects:
  - banana_ycb_robolab
  - plate_large_vomp_robolab
task: PickAndPlaceTask
# The production schema requires complete structured asset/task records.
`;
interface RequestExample { mode: 'new' | 'refine'; prompt: string; family: string; model: string; robot: string; policy: string; calls: number; source: PreviewSelection | null; }
export function EnvironmentPanel({ selection, draft, prompt, onDraft, onPrompt, onApplyExample, onComposerDirty, onOpenVisualizer, hideDraftWorkspace = false }: EnvironmentPanelProps) {
 const [mode, setMode] = useState<'new' | 'refine'>('new');
 const [feedback, setFeedback] = useState('');
 const [family, setFamily] = useState('example-a2');
 const [model, setModel] = useState('Example approved model profile');
 const [robot, setRobot] = useState('DROID');
 const [policy, setPolicy] = useState('Allow disclosed fallback');
 const [calls, setCalls] = useState(8);
 const [tab, setTab] = useState(hideDraftWorkspace ? 'Evidence' : 'Specification');
 const [error, setError] = useState('');
 const [request, setRequest] = useState<RequestExample | null>(null);
 const [candidate, setCandidate] = useState<string | null>(null);
 const [review, setReview] = useState(false);
 const [evidence, setEvidence] = useState('No retrieval performed');
 const [node, setNode] = useState('banana');
 useEffect(() => { onComposerDirty?.(Boolean(feedback.trim() || request || candidate)); }, [feedback, request, candidate, onComposerDirty]);
 function preview() {
  const text = mode === 'new' ? prompt : feedback;
  if (!text.trim()) { setError(mode === 'new' ? 'Enter a prompt before reviewing a request.' : 'Enter refinement feedback.'); return; }
  if (mode === 'refine' && !selection) { setError('Select an exact source version for refinement.'); return; }
  if (!family.trim() || !Number.isInteger(calls) || calls < 1 || calls > 8) { setError('Enter a family and a call limit between 1 and 8.'); return; }
  setError(''); setCandidate(null); setReview(false);
  setRequest({ mode, prompt: text, family, model, robot: mode === 'new' ? robot : selection!.robot, policy: mode === 'new' ? policy : 'No retrieval added to Refine', calls, source: mode === 'refine' && selection ? { ...selection } : null });
 }
 return <div className="preview-environment">
  <section className="preview-panel preview-compose" aria-labelledby="compose-heading">
   <div className="preview-section-heading"><span className="preview-eyebrow">01 / AUTHOR</span><h2 id="compose-heading">Define the environment</h2></div>
   <p className="preview-muted">Start with intent. Inspect a candidate before applying it. No model is called in this preview.</p>
   <fieldset className="preview-mode"><legend>Creation mode</legend>
    <label><input type="radio" name="preview-generation-mode" checked={mode === 'new'} onChange={() => setMode('new')} /> New environment</label>
    <label><input type="radio" name="preview-generation-mode" checked={mode === 'refine'} disabled={!selection} onChange={() => setMode('refine')} /> Refine selected version</label>
   </fieldset>
   <label className="preview-field">{mode === 'new' ? 'Scenario prompt' : 'Refinement feedback'}<textarea aria-label={mode === 'new' ? 'Scenario prompt' : 'Refinement feedback'} rows={5} maxLength={12000} value={mode === 'new' ? prompt : feedback} onChange={e => mode === 'new' ? onPrompt(e.target.value) : setFeedback(e.target.value)} placeholder="Describe the robot, objects and intended task…" /></label>
   <button className="quiet" onClick={() => { setMode('new'); onPrompt('Droid grasps the yellow banana from the right side of the maple table and places it onto the large white ceramic plate on the left.'); }}>Use A2 example prompt</button>
   <div className="preview-grid">
    <label className="preview-field">Scenario family<input value={family} maxLength={100} onChange={e => setFamily(e.target.value)} /></label>
    <label className="preview-field">Model profile<select value={model} onChange={e => setModel(e.target.value)}><option>Example approved model profile</option><option>Example alternate model profile</option></select></label>
   </div>
   {mode === 'new' ? <label className="preview-field">Retrieval policy<select value={policy} onChange={e => setPolicy(e.target.value)}><option>Allow disclosed fallback</option><option>Require retrieval service</option><option>Explicit no-retrieval experiment</option></select></label> : <p className="preview-muted">Frozen source: {selection?.versionId}. Refine does not silently add retrieval.</p>}
   <details><summary>Constraints and budget</summary><div className="preview-grid">
    <label className="preview-field">Robot constraint<select disabled={mode === 'refine'} value={mode === 'new' ? robot : selection?.robot ?? ''} onChange={e => setRobot(e.target.value)}><option>DROID</option><option>G1 — left-hand profile</option>{mode === 'refine' && selection && <option>{selection.robot}</option>}</select></label>
    <label className="preview-field">Maximum model calls<input type="number" min={1} max={8} value={Number.isNaN(calls) ? '' : calls} onChange={e => setCalls(e.target.valueAsNumber)} /></label>
   </div><p className="preview-muted">Example interactive limit, not a live spend authorization. Catalogue/profile compatibility is reviewed separately.</p></details>
   {error && <p role="alert">{error}</p>}
   <div className="preview-actions"><button className="primary" onClick={preview}>Preview generation request</button><span className="preview-tag">No submission</span></div>
  </section>
  <section className="preview-panel preview-document" aria-label={hideDraftWorkspace ? 'Generation reference examples' : 'Draft workspace'}>
   <div className="preview-section-heading"><span className="preview-eyebrow">02 / INSPECT</span><h2>{hideDraftWorkspace ? 'Generation reference examples' : 'Draft workspace'}</h2></div>
   <div className="preview-tabs" role="tablist" aria-label="Environment views">{(hideDraftWorkspace ? ['Authored graph', 'Evidence'] : ['Specification', 'Authored graph', 'Preview', 'Evidence']).map(t => <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>{t}</button>)}</div>
   {!hideDraftWorkspace && <div hidden={tab !== 'Specification'}><label className="preview-field">Draft YAML<textarea aria-label="Draft YAML" className="preview-code" rows={17} value={draft} maxLength={64000} onChange={e => onDraft(e.target.value)} placeholder="# No source document required for New" /></label><p className="preview-muted">Editable local draft · no schema validation or disk save performed.</p></div>}
   {tab === 'Authored graph' && <div><p className="preview-muted">Illustrative A2 authored relationships, not a parse of the current draft and not persisted Neo4j data.</p><div className="preview-graph-nodes">{['robot', 'table', 'banana', 'plate'].map(n => <button key={n} aria-pressed={node === n} onClick={() => setNode(n)}>{n}</button>)}</div><table className="preview-table"><thead><tr><th>Subject</th><th>Relationship</th><th>Reference</th></tr></thead><tbody><tr><td>banana</td><td>initially on</td><td>table</td></tr><tr><td>plate</td><td>initially on</td><td>table</td></tr><tr><td>robot</td><td>task destination</td><td>plate</td></tr></tbody></table><p>Inspecting example node: <strong>{node}</strong>. Physical pose and reachability are not measured.</p></div>}
   {tab === 'Preview' && <div className="preview-empty"><h3>Assets & scene visualizer</h3><p>Open saved historical asset and scene captures, inspect camera availability and review future render settings. Historical images are not renders of this editable draft.</p><button type="button" disabled={!onOpenVisualizer} onClick={onOpenVisualizer}>Open Assets & scene</button><p className="preview-muted">Image zoom is local. No live renderer, stream or GPU job is connected.</p></div>}
   {tab === 'Evidence' && <div><label className="preview-field">Inspect example retrieval state<select value={evidence} onChange={e => setEvidence(e.target.value)}>{['No retrieval performed', 'Measured-prior example', 'Structural-prior example', 'No eligible priors', 'Retrieval unavailable'].map(s => <option key={s}>{s}</option>)}</select></label><h3>{evidence}</h3><p>Real evidence would show exact source revisions, consumed context, deciding run, policy identity and receipt digest. No measured metrics or verified receipt are loaded here.</p><dl className="preview-facts"><dt>Schema validity</dt><dd>Not checked</dd><dt>Published</dt><dd>Not performed</dd><dt>Physical task success</dt><dd>Not evaluated</dd></dl></div>}
  </section>
  {request && <section className="preview-panel preview-request" aria-label="Frozen example request"><span className="preview-eyebrow">03 / REVIEW — EXAMPLE ONLY</span><h2>Execution summary</h2><div data-testid="request-summary"><dl className="preview-facts"><dt>Operation</dt><dd>{request.mode}</dd><dt>Prompt</dt><dd>{request.prompt}</dd><dt>Family</dt><dd>{request.family}</dd><dt>Source</dt><dd>{request.source?.versionId ?? 'No base document'}</dd><dt>Model</dt><dd>{request.model}</dd><dt>Robot</dt><dd>{request.robot}</dd><dt>Retrieval</dt><dd>{request.policy}</dd><dt>Call limit</dt><dd>{request.calls}</dd><dt>Side effects</dt><dd>None in preview. Real save, publish, build and evaluation require separate decisions.</dd></dl></div><div className="preview-actions"><button onClick={() => { setCandidate(request.source ? `${request.source.yaml}\n# Example refinement proposal; not model output.\n` : A2_EXAMPLE); setReview(false); }}>Show example candidate</button><button onClick={() => { setRequest(null); setCandidate(null); setReview(false); }}>Close request review</button></div>
   {candidate && <div className="preview-candidate"><h3>Example candidate · not generated</h3><p className="preview-muted">This local fixture illustrates the review flow; it does not fulfill arbitrary prompts.</p><pre>{candidate}</pre><button onClick={() => setReview(true)}>Review example candidate</button>{review && <div><h4>Replace the editable draft?</h4><p>The saved source stays unchanged. New or mismatched-source candidates open as a detached draft.</p><div className="preview-diff"><div><h4>Current draft</h4><pre>{draft || '(empty)'}</pre></div><div><h4>Example proposal</h4><pre>{candidate}</pre></div></div><button onClick={() => { const detached = request.mode === 'new' || request.source?.versionId !== selection?.versionId; if (onApplyExample) onApplyExample(candidate, detached); else onDraft(candidate); setTab(hideDraftWorkspace ? 'Evidence' : 'Specification'); setReview(false); }}>Apply example to draft</button><button onClick={() => setReview(false)}>Keep current draft</button></div>}</div>}
  </section>}
 </div>;
}
