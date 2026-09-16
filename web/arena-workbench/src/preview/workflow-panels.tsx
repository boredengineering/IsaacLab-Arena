import React, { useEffect, useState } from 'react';
import type { PreviewContext, PreviewSection } from './types';

type Section = Exclude<PreviewSection, 'environment' | 'library' | 'coverage' | 'neo4j' | 'jobs' | 'visualizer'>;
type Fields = Record<string, string | boolean>;
function Select({ label, value, options, onChange }: { label: string; value: string; options: string[][]; onChange: (value: string) => void }) {
  return <label className="preview-field">{label}<select aria-label={label} value={value} onChange={event => onChange(event.target.value)}>{options.map(([id, text]) => <option key={id} value={id}>{text ?? id}</option>)}</select></label>;
}
function Input({ label, value, onChange, min, max, multiline = false }: { label: string; value: string; onChange: (value: string) => void; min?: number; max?: number; multiline?: boolean }) {
  return <label className="preview-field">{label}{multiline ? <textarea aria-label={label} maxLength={4000} value={value} onChange={event => onChange(event.target.value)} /> : <input aria-label={label} type={min === undefined ? 'text' : 'number'} min={min} max={max} maxLength={200} value={value} onChange={event => onChange(event.target.value)} />}</label>;
}
function Check({ label, checked, onChange, disabled = false }: { label: string; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  return <label className="preview-field"><input type="checkbox" checked={checked} disabled={disabled} onChange={event => onChange(event.target.checked)} />{label}</label>;
}
const integer = (value: string, min: number, max: number) => /^\d+$/.test(value) && Number.isSafeInteger(Number(value)) && Number(value) >= min && Number(value) <= max;
const savedSource = (context: PreviewContext) => !!context.familyId && !!context.versionId && !context.dirty;
function RequestReview({ context, action, fields, validate = () => '', blocked = false, requiresSaved = false }: { context: PreviewContext; action: string; fields: Fields; validate?: () => string; blocked?: boolean; requiresSaved?: boolean }) {
  const [error, setError] = useState('');
  const [frozen, setFrozen] = useState<string | null>(null);
  return <><div className="preview-actions"><button type="button" disabled={blocked} onClick={() => { const issue = requiresSaved && !savedSource(context) ? 'Select a clean saved example version and explicitly rebind this form; draft identity is unresolved and not captured.' : Object.values(fields).some(value => typeof value === 'string' && value.length > 4000) ? 'Each local request field is limited to 4000 characters.' : validate(); setError(issue); if (!issue && !frozen) setFrozen(JSON.stringify({ exampleOnly: true, intendedAction: action, sourceStatus: savedSource(context) ? 'saved example revision only — draft not captured' : 'unresolved — draft not captured', context: { ...context }, options: { ...fields } }, null, 2)); }}>Preview request</button></div>
    {error && <p role="alert">{error}</p>}
    {frozen && <section aria-label="Request confirmation" className="preview-panel"><h3>Review confirmation</h3><p>No action dispatched. These example source labels and options are frozen; no draft content or exact draft identity was captured. Later edits and rebinding do not retarget this review. Use Back to form before reviewing another request.</p><pre data-testid="frozen-request">{frozen}</pre><button type="button" onClick={() => setFrozen(null)}>Back to form</button></section>}
  </>;
}
function BuildPanel({ context }: { context: PreviewContext }) {
  const [purpose, setPurpose] = useState('snapshot');
  const [steps, setSteps] = useState('120');
  const [reset, setReset] = useState('1');
  const [controller, setController] = useState('zero-action');
  const [scope, setScope] = useState('scene');
  const [camera, setCamera] = useState('example-overview');
  const [prompt, setPrompt] = useState('');
  const [calls, setCalls] = useState('2');
  const [policy, setPolicy] = useState('example-gr00t');
  const [identity, setIdentity] = useState('');
  const [episodes, setEpisodes] = useState('5');
  const [seed, setSeed] = useState('42');
  const [recording, setRecording] = useState(false);
  const [ownership, setOwnership] = useState(false);
  useEffect(() => setOwnership(false), [context]);
  const [nativeOperation, setNativeOperation] = useState('launch');
  const [nativeSession, setNativeSession] = useState('absent');
  const [device, setDevice] = useState('example-gpu');
  const [solver, setSolver] = useState('example-default');
  const [outcome, setOutcome] = useState('empty');
  return <section className="preview-panel"><h2>Build & evaluate</h2><Select label="Build purpose" value={purpose} onChange={setPurpose} options={[[ 'snapshot', 'Snapshot'], ['build', 'Build / zero-action'], ['generate-build', 'Generate-and-build'], ['evaluate', 'Policy evaluation'], ['nativeKit', 'Native Kit']]} />
    <p className="preview-muted">Bound source: {context.versionId ?? 'Unsaved draft'} · {savedSource(context) ? 'Saved example only; draft not captured' : 'Unresolved draft — not captured'}. Examples are not runtime evidence.</p>
    {purpose === 'build' && <><p>Reset and bounded stepping check scene construction, not policy success. Zero-action is not posture-hold.</p><div className="preview-grid"><Input label="Step limit" value={steps} onChange={setSteps} min={1} max={10000} /><Input label="Reset count" value={reset} onChange={setReset} min={1} max={20} /><Select label="Build controller" value={controller} onChange={setController} options={[[ 'zero-action'], ['posture-hold']]} /></div></>}
    {purpose === 'snapshot' && <><p>Scene or asset still image only; never simulation-success evidence. Missing and stale pixels remain unavailable.</p><Select label="Snapshot scope" value={scope} onChange={setScope} options={[[ 'scene'], ['asset', 'Example asset only']]} /><Select label="Camera profile" value={camera} onChange={setCamera} options={[[ 'example-overview'], ['example-closeup']]} /></>}
    {purpose === 'generate-build' && <><Input label="Generation prompt" value={prompt} onChange={setPrompt} multiline /><Input label="Model call budget" value={calls} onChange={setCalls} min={1} max={10} /><Input label="Generated build step limit" value={steps} onChange={setSteps} min={1} max={10000} /><p>Stage 1 proposes example-candidate; stage 2 builds that exact candidate, not a later edited draft. Generation is retained if build fails. Applying it to the editor is a separate review.</p></>}
    {purpose === 'evaluate' && <><div className="preview-grid"><Select label="Approved policy profile" value={policy} onChange={setPolicy} options={[[ 'example-gr00t', 'Example GR00T checkpoint'], ['example-openpi', 'Example OpenPI server']]} /><Input label="Checkpoint or server identity" value={identity} onChange={setIdentity} /><Input label="Episode limit" value={episodes} onChange={setEpisodes} min={1} max={100} /><Input label="Seed" value={seed} onChange={setSeed} min={0} max={2147483647} /></div><p>Policy identity: {identity.trim() ? 'supplied example — not verified' : 'missing — not verified'}. Fixed scene; embodiment, action-space and camera compatibility require runtime verification. No policy adapter is connected.</p><Check label="Record example camera stream" checked={recording} onChange={setRecording} /></>}
    {purpose === 'nativeKit' && <><p>Native Kit is not browser 3D, a screenshot, or a recording. An operator-managed interactive display session requires a supported native adapter; none is connected here.</p><p>Display profile: example-local-display. Launch and close belong to the requesting owner; closing must await cleanup, not merely hide this panel.</p><Select label="Native session operation" value={nativeOperation} onChange={setNativeOperation} options={[[ 'launch'], ['close']]} /><Select label="Native session example" value={nativeSession} onChange={setNativeSession} options={[[ 'absent'], ['owned', 'example-native-session (owned)'], ['foreign', 'Example session owned by another user'], ['cleanup-pending']]} /><Check label="Review native session ownership and close responsibility" checked={ownership} onChange={setOwnership} /></>}
    <details><summary>Advanced approved profiles & effective options</summary><div className="preview-grid"><Select label="Device profile" value={device} onChange={setDevice} options={[[ 'example-gpu'], ['example-cpu', 'Example CPU (policy support unverified)']]} /><Select label="Solver profile" value={solver} onChange={setSolver} options={[[ 'example-default'], ['example-stable']]} /></div><p>Rendering: example headless except Native Kit. Distribution: single worker. Animation: unchanged. Recording is evaluation-only. Arbitrary GPU indices, display sockets, shell commands and host paths are rejected; approved operator profiles must supply effective runtime values. Profile names are illustrative, not discovered readiness.</p></details>
    <RequestReview requiresSaved={purpose !== 'generate-build'} context={context} action={purpose === 'nativeKit' ? `nativeKit ${nativeOperation}` : purpose} fields={{ purpose, steps, reset, controller, scope, camera, prompt, calls, policy, identity, episodes, seed, recording, ownership, nativeOperation, nativeSession, device, solver }} validate={() => {
      if ((purpose === 'build' || purpose === 'generate-build') && (!integer(steps, 1, 10000) || !integer(reset, 1, 20))) return 'Step limit must be 1–10000 and reset count 1–20 (whole numbers).';
      if (purpose === 'generate-build' && (!prompt.trim() || !integer(calls, 1, 10))) return 'Generation prompt is required; model call budget must be 1–10.';
      if (purpose === 'evaluate' && !identity.trim()) return 'Supply an example checkpoint or server identity; missing identity is not verified.';
      if (purpose === 'evaluate' && (!integer(episodes, 1, 100) || !integer(seed, 0, 2147483647))) return 'Episode limit must be 1–100 and seed 0–2147483647.';
      if (purpose === 'nativeKit' && !ownership) return 'Review native session ownership before previewing launch.';
      if (purpose === 'nativeKit' && nativeSession === 'cleanup-pending') return 'Native cleanup is pending; observe release before launch or another close request.';
      if (purpose === 'nativeKit' && nativeOperation === 'close' && nativeSession !== 'owned') return 'Close requires an exact owned native session.';
      if (purpose === 'nativeKit' && nativeOperation === 'launch' && nativeSession !== 'absent') return 'An existing native session must be resolved before a new launch.';
      return '';
    }} />
    <Select label="Build example state" value={outcome} onChange={setOutcome} options={[[ 'empty'], ['loading'], ['candidate'], ['failed'], ['cancelled'], ['stale']]} />
    <p role="status">Example {outcome}: {outcome === 'failed' ? 'Build diagnostics unavailable; any completed generation remains a candidate, not accepted.' : outcome === 'candidate' ? 'Candidate only: no persistence, publication or evaluation implied.' : 'No measured artifacts. Change the selector explicitly; no job is running.'}</p>
  </section>;
}
// Synthetic failure scenarios only: Library source labels, never measured runs or receipts.
const repairEvidence = [
  { exampleOnly: true, id: 'example-c1-failed-run', familyId: 'example-c1-g1-tabletop', versionId: 'example-c1-g1-tabletop-v1', sceneConfigIdentity: 'example-library/example-c1-g1-tabletop/v1.yaml', policyIdentity: 'example-c1-gr00t', policyConfigIdentity: 'example-c1-policy-config-v1', checkpointOrServerIdentity: 'example-c1-checkpoint' },
  { exampleOnly: true, id: 'example-a2-failed-run', familyId: 'example-a2-droid', versionId: 'example-a2-droid-v1', sceneConfigIdentity: 'example-library/example-a2-droid/v1.yaml', policyIdentity: 'example-a2-openpi', policyConfigIdentity: 'example-a2-policy-config-v1', checkpointOrServerIdentity: 'example-a2-server' },
];
function ImprovePanel({ context }: { context: PreviewContext }) {
  const [workflow, setWorkflow] = useState('repair');
  const [evidence, setEvidence] = useState('example-c1-failed-run');
  const [repairPolicy, setRepairPolicy] = useState('example-c1-gr00t');
  const [repairPolicyConfig, setRepairPolicyConfig] = useState('example-c1-policy-config-v1');
  const failedEvidence = repairEvidence.find(item => item.id === evidence);
  const evidenceIssue = !failedEvidence ? 'No failed evidence selected — repair blocked.'
    : !savedSource(context) ? 'Select a clean saved example and rebind; draft identity unresolved — not captured.'
    : failedEvidence.familyId !== context.familyId || failedEvidence.versionId !== context.versionId ? 'Evidence family/version mismatch — repair blocked for this bound source.'
    : failedEvidence.policyIdentity !== repairPolicy || failedEvidence.policyConfigIdentity !== repairPolicyConfig ? 'Evidence policy/config mismatch or identity missing — repair blocked.' : '';
  const [repairMode, setRepairMode] = useState('scene');
  const [feedback, setFeedback] = useState('');
  const [objective, setObjective] = useState('Improve task completion without changing the target scene contract');
  const [iterations, setIterations] = useState('3');
  const [budget, setBudget] = useState('20');
  const [resume, setResume] = useState('new');
  const [mode, setMode] = useState('observe');
  const [consentedScope, setConsentedScope] = useState<string | null>(null);
  useEffect(() => setConsentedScope(null), [context]);
  const [offset, setOffset] = useState('5');
  const consentScope = JSON.stringify({ context, mode, offset });
  const consent = consentedScope === consentScope;
  const setConsent = (value: boolean) => setConsentedScope(value ? consentScope : null);
  const [outcome, setOutcome] = useState('empty');
  const supported = context.robot.toLowerCase() === 'g1' && context.hand.toLowerCase() === 'left';
  const acceptanceEligible = savedSource(context) && (workflow === 'repair' ? !evidenceIssue : supported);
  const [acceptedFor, setAcceptedFor] = useState<PreviewContext | null>(null);
  const accepted = acceptedFor === context && acceptanceEligible;
  const setAccepted = (value: boolean) => setAcceptedFor(value && acceptanceEligible ? context : null);
  useEffect(() => setAcceptedFor(null), [context, workflow, evidence, repairPolicy, repairPolicyConfig, repairMode, feedback, objective, iterations, budget, resume, mode, offset]);
  return <section className="preview-panel"><h2>Improve</h2><Select label="Improvement workflow" value={workflow} onChange={setWorkflow} options={[[ 'repair', 'Evidence-bound repair'], ['dcrg', 'DCRG refinement / resume'], ['assistance', 'Controller assistance']]} />
    {workflow === 'repair' && <><Select label="Failed evidence" value={evidence} onChange={setEvidence} options={[...repairEvidence.map(item => [item.id, `${item.id} / ${item.versionId} (synthetic)`]), ['missing', 'No evidence available']]} />
      <Select label="Repair policy identity" value={repairPolicy} onChange={setRepairPolicy} options={[...repairEvidence.map(item => [item.policyIdentity]), ['missing', 'Policy identity missing']]} />
      <Select label="Repair policy configuration" value={repairPolicyConfig} onChange={setRepairPolicyConfig} options={[...repairEvidence.map(item => [item.policyConfigIdentity]), ['missing', 'Policy config identity missing']]} />
      <section aria-label="Repair evidence binding"><h3>Illustrative failed-evidence binding — not runtime evidence</h3>{failedEvidence ? <pre>{JSON.stringify(failedEvidence, null, 2)}</pre> : <p>No failed-evidence fixture selected.</p>}<p>Only the listed v1 fixtures have illustrative failed evidence. Other versions have none: evidence is not inherited from a family, robot, hand or newer selection. Config identities are local example labels, not verified hashes or receipts. No measured diagnostics, episodes or policy success are available.</p></section>
      <p role="status" aria-label="Repair evidence status">{evidenceIssue || 'Example family/version and policy/config match — not runtime verification.'}</p>
      <Select label="Repair mode" value={repairMode} onChange={setRepairMode} options={[[ 'scene', 'Scene configuration'], ['policy-config', 'Policy configuration (checkpoint unchanged)']]} /><Input label="Repair feedback" value={feedback} onChange={setFeedback} multiline /><p>Example diagnostics: contact constraint unavailable. Prior failure evidence is retained. Reevaluation requires separate authorization; accepting a proposal neither executes nor saves it.</p></>}
    {workflow === 'dcrg' && <><p>DCRG is controlled iterative refinement, not ordinary healing. Example contract: G1 left-hand pick-and-place with an approved GR00T policy; other scenarios and checkpoints require independent capability verification.</p><Input label="Refinement objective" value={objective} onChange={setObjective} multiline /><div className="preview-grid"><Input label="Iteration limit" value={iterations} onChange={setIterations} min={1} max={10} /><Input label="Cumulative episode budget" value={budget} onChange={setBudget} min={1} max={100} /><Select label="Resume point" value={resume} onChange={setResume} options={[[ 'new', 'New lineage'], ['example-iteration-2', 'Example iteration 2 / retained candidate'], ['unknown', 'Unknown resume identity — blocked']]} /></div><p>Lineage: example-parent → example-iteration-2. Resume binds that exact candidate, policy and consumed budget; a new budget does not reset prior consumption. Current iteration is unavailable unless selected as an example.</p></>}
    {workflow === 'assistance' && <><p>Supported contract: G1 left hand only; this is not DROID assistance. Scene, controller and checkpoint remain fixed. Observe records traces; offset changes controller targets; gate restricts intervention; combined uses both.</p><Select label="Assistance mode" value={mode} onChange={value => { setMode(value); setConsent(false); }} options={[[ 'observe'], ['offset'], ['gate'], ['combined']]} /><Check label="Consent to privileged-state example review" checked={consent} onChange={setConsent} /><details><summary>Advanced assistance, trial & trace details</summary><Input label="Maximum offset (mm)" value={offset} onChange={value => { setOffset(value); setConsent(false); }} min={0} max={50} /><p>Example controller: example-g1-left; checkpoint: example-checkpoint (not verified). Trace artifacts: observations, offsets, gates and interventions. Trial registration is distinct from attaching evidence. Zero-success retrieval must retain the denominator and failed trials, not invent successful priors.</p></details></>}
    <RequestReview requiresSaved blocked={workflow === 'repair' && !!evidenceIssue} context={context} action={workflow} fields={{ workflow, evidence, evidenceBinding: failedEvidence ? JSON.stringify(failedEvidence) : 'unavailable', repairPolicy, repairPolicyConfig, repairMode, feedback, objective, iterations, budget, resume, mode, consent, offset }} validate={() => {
      if (workflow === 'repair' && (evidenceIssue || !feedback.trim())) return evidenceIssue || 'Provide repair feedback for the matched example evidence.';
      if (workflow !== 'repair' && !supported) return 'Only the G1 left-hand example contract is supported; DROID is not interchangeable.';
      if (workflow === 'dcrg' && (!objective.trim() || !integer(iterations, 1, 10) || !integer(budget, 1, 100) || resume === 'unknown')) return 'Objective, bounded iteration/budget and an exact known resume point are required.';
      if (workflow === 'assistance' && !consent) return 'Explicit privileged-state consent is required, including observation of privileged state.';
      if (workflow === 'assistance' && !integer(offset, 0, 50)) return 'Maximum offset must be 0–50 whole millimeters.';
      return '';
    }} />
    <Select label="Improvement example state" value={outcome} onChange={value => { setOutcome(value); setAccepted(false); }} options={[[ 'empty'], ['candidate'], ['failed'], ['blocked'], ['cancelled']]} />
    {outcome === 'candidate' ? <section className="preview-panel"><h3>Example proposed diff — not applied</h3><pre>- solver: example-default{'\n'}+ solver: example-stable</pre><Check label="Accept example proposal locally (no editor change)" checked={accepted} disabled={!acceptanceEligible} onChange={setAccepted} /><p>{accepted ? 'Example acceptance reviewed; saving and reevaluation remain separate.' : 'Proposal remains unaccepted.'}</p></section> : <p role="status">Example {outcome}: no accepted changes or measured outcomes.</p>}
  </section>;
}
function ExperimentsPanel({ context }: { context: PreviewContext }) {
  const [format, setFormat] = useState('typed');
  const [input, setInput] = useState('{"type":"experiment","name":"example-study"}');
  const [legacy, setLegacy] = useState('name: example-study');
  const [seeds, setSeeds] = useState('1,2');
  const [episodes, setEpisodes] = useState('5');
  const [budget, setBudget] = useState('20');
  const [failure, setFailure] = useState('stop');
  const [rebuild, setRebuild] = useState(true);
  const [state, setState] = useState('unattempted');
  const parsedSeeds = seeds.split(',').map(value => value.trim());
  const seedsValid = parsedSeeds.length <= 8 && parsedSeeds.every(value => integer(value, 0, 2147483647)) && new Set(parsedSeeds.map(Number)).size === parsedSeeds.length;
  const children = seedsValid && integer(episodes, 1, 100) ? parsedSeeds.map((seed, index) => ({ id: `example-child-${index + 1}`, seed: Number(seed), episodes: Number(episodes), rebuild, versionId: savedSource(context) ? context.versionId : null, policy: 'example-policy (not verified)' })) : [];
  const cumulative = children.reduce((sum, child) => sum + child.episodes, 0);
  function validate() {
    if (format === 'typed') {
      try { const data: unknown = JSON.parse(input); if (!data || typeof data !== 'object' || !('type' in data) || data.type !== 'experiment' || !('name' in data) || typeof data.name !== 'string' || !/^example-[\w-]{1,80}$/.test(data.name) || Object.keys(data).some(key => !['type', 'name'].includes(key))) return 'Typed input requires type experiment and an example-* name; unknown fields are not supported in this local preview.'; }
      catch { return 'Invalid JSON: use the documented local typed input shape.'; }
    } else if (!/^name:\s*example-[\w-]{1,80}\s*$/.test(legacy)) return 'Legacy preview accepts only name: example-*; full YAML/includes require the future approved importer.';
    if (!seedsValid) return 'Provide 1–8 unique whole-number seeds in 0–2147483647.';
    if (!integer(episodes, 1, 100) || !integer(budget, 1, 800) || cumulative > Number(budget)) return 'Episode limits must be bounded and cumulative child episodes must fit the total episode budget.';
    return '';
  }
  return <section className="preview-panel"><h2>Experiments</h2><p>Local experiment plan only. No children have been submitted. Typed and legacy input are explicit, never inferred from a host path.</p><Select label="Import format" value={format} onChange={setFormat} options={[[ 'typed', 'Typed experiment JSON'], ['legacy', 'Legacy input review']]} /><Input label="Experiment input" value={format === 'typed' ? input : legacy} onChange={format === 'typed' ? setInput : setLegacy} multiline /><p className="preview-muted">Preview subset: typed JSON accepts type and example name; legacy accepts one name line. Full schema, include resolution, and import execution are unavailable.</p><div className="preview-grid"><Input label="Variation seeds" value={seeds} onChange={setSeeds} /><Input label="Episodes per child" value={episodes} onChange={setEpisodes} min={1} max={100} /><Input label="Total episode budget" value={budget} onChange={setBudget} min={1} max={800} /><Select label="Failure policy" value={failure} onChange={setFailure} options={[[ 'stop', 'Stop on first failure'], ['continue', 'Continue on child error within remaining budget']]} /></div><Check label="Rebuild for each ordered child" checked={rebuild} onChange={setRebuild} />
    <details open><summary>Variations & effective child configurations</summary><table className="preview-table" aria-label="Effective child configurations"><thead><tr><th>Order / child</th><th>Seed</th><th>Episodes</th><th>Exact revision</th><th>Rebuild</th></tr></thead><tbody>{children.map(child => <tr key={child.id}><td>{child.id}</td><td>{child.seed}</td><td>{child.episodes}</td><td>{child.versionId ?? 'Draft not captured — identity unresolved'}</td><td>{child.rebuild ? 'Required' : 'Reuse subject to compatibility'}</td></tr>)}</tbody></table>{!children.length && <p>No valid children. Correct seeds and episode limits.</p>}<p>Planned cumulative episodes: {cumulative}; this is a budget calculation, not a result. Children execute in displayed order; stop/cancellation leaves later children unattempted.</p></details>
    <details><summary>Advanced child overrides and prerequisites</summary><p>Variation axis in this preview: seed. Scene revision and example-policy are inherited unchanged. Arbitrary overrides, distribution, nested includes and policy compatibility are unresolved until approved schema/profile adapters exist.</p></details>
    <RequestReview requiresSaved context={context} action="ordered experiment children" fields={{ format, input: format === 'typed' ? input : legacy, seeds, episodes, budget, failure, rebuild, effectiveChildren: JSON.stringify(children) }} validate={validate} />
    <Select label="Experiment example state" value={state} onChange={setState} options={[[ 'unattempted'], ['partial'], ['failed'], ['cancelled']]} /><p role="status">Example {state}: {state === 'partial' ? 'A child has partial artifacts; remaining children are unattempted. No aggregate success statistic is available.' : 'No measured aggregate or completed episode denominator is available.'}</p>
  </section>;
}
const exampleRuns = [
  { id: 'example-queued', state: 'queued', stage: 'Waiting for owner resources', episodes: null },
  { id: 'example-active', state: 'active', stage: 'Evaluation (illustrative)', episodes: null },
  { id: 'example-zero-episodes', state: 'failed', stage: 'Policy identity unresolved', episodes: 0 },
  { id: 'example-cleanup-pending', state: 'cleanup-pending', stage: 'Cancellation / resource release unconfirmed', episodes: null },
  { id: 'example-unknown', state: 'unknown', stage: 'Acknowledgement unavailable', episodes: null },
  { id: 'example-cancelled', state: 'cancelled', stage: 'Terminal cancellation example', episodes: null },
];
function RunsPanel() {
  const [selected, setSelected] = useState('example-queued');
  const [availability, setAvailability] = useState('examples');
  const [artifact, setArtifact] = useState('report');
  const [compare, setCompare] = useState('none');
  const run = exampleRuns.find(item => item.id === selected)!;
  const context: PreviewContext = { familyId: 'example-run-scene', versionId: 'example-run-scene-v1', familyName: 'Run-bound example scene', versionLabel: 'Example v1', robot: 'Unverified', hand: 'Unverified', dirty: false };
  return <section className="preview-panel"><h2>Runs & evidence</h2><p>Research reports, metrics and media examples. Job cancellation, authorization and integration diagnostics belong in Jobs & diagnostics.</p><Select label="Research evidence availability" value={availability} onChange={setAvailability} options={[[ 'examples'], ['empty'], ['loading'], ['error']]} />
    {availability === 'examples' ? <table className="preview-table" aria-label="Example research runs"><thead><tr><th>Run</th><th>Example state</th><th>Evidence</th></tr></thead><tbody>{exampleRuns.map(item => <tr key={item.id}><td>{item.id}</td><td><span className="preview-tag">{item.state}</span></td><td>No measured artifacts</td></tr>)}</tbody></table> : <p role="status">Example {availability}: research evidence unavailable. No report, metrics or job result is inferred.</p>}
    <Select label="Selected example run" value={selected} onChange={value => { setSelected(value); if (value === compare) setCompare('none'); }} options={exampleRuns.map(item => [item.id])} /><section className="preview-panel"><h3>{run.id} · example detail</h3><p>Scene: example-run-scene-v1; policy identity: missing — not verified. These run identities do not follow the editable draft selection.</p><p>Stage: {run.stage}</p><ol aria-label="Example run stages"><li>Admission: {run.state === 'unknown' ? 'unknown' : 'example only'}</li><li>Build: no verified receipt</li><li>Evaluation: {run.stage}</li><li>Evidence: unavailable or partial</li><li>Cleanup: {run.state === 'cleanup-pending' ? 'pending' : 'not independently verified'}</li></ol><p>Completed episodes: {run.episodes === null ? 'unavailable (null)' : run.episodes}</p><p>Success rate: unavailable (null)</p><p>Reward / duration: unavailable (null). Empty denominators never become zero-success statistics.</p>
    {run.state === 'cleanup-pending' && <p role="status">Cancellation requested; cleanup still pending. Resources must not be described as released.</p>}
    {run.state === 'unknown' && <p role="status">Unknown outcome: retain exact request identity and observe first. No blind retry or automatic resubmission.</p>}
    <Select label="Evidence view" value={artifact} onChange={setArtifact} options={[[ 'report'], ['metrics'], ['video'], ['diagnostics']]} /><p>Example {artifact} artifact: unavailable. No invented file, playable media or measured chart. Failed / partial artifacts remain attributed to {run.id}.</p>
    <details><summary>Compare exact run identities</summary><Select label="Comparison example run" value={compare} onChange={setCompare} options={[[ 'none', 'No comparison selected'], ...exampleRuns.filter(item => item.id !== selected).map(item => [item.id])]} /><p>{compare === 'none' ? 'Select a second example to inspect attribution.' : `${selected} versus ${compare}: metrics unavailable; scene/policy compatibility and denominators must match before comparison.`}</p></details></section>
    <RequestReview context={context} action="inspect research evidence" fields={{ selectedRun: selected, runScene: 'example-run-scene-v1', policyIdentity: 'missing', artifact, compare, runState: run.state }} validate={() => compare === selected ? 'Comparison run must differ from the selected run.' : ''} />
    <p className="preview-muted">Diagnostic evidence artifacts describe a research run; they do not launch operational integration diagnostics.</p>
  </section>;
}
function GraphPanel({ context }: { context: PreviewContext }) {
  const [view, setView] = useState('persisted');
  const [query, setQuery] = useState('');
  const [graphState, setGraphState] = useState('example');
  const [state, setState] = useState('empty');
  const [operation, setOperation] = useState('prepare');
  const [target, setTarget] = useState('example-research');
  const [consent, setConsent] = useState(false);
  const [reconcileConsent, setReconcileConsent] = useState(false);
  useEffect(() => { setConsent(false); setReconcileConsent(false); }, [context]);
  const [prepared, setPrepared] = useState<{ context: PreviewContext; target: string } | null>(null);
  const [selectedNode, setSelectedNode] = useState('example-scene');
  const nodes = ['example-scene', 'example-task', 'example-asset'].filter(node => node.includes(query.toLowerCase()));
  const blocked = operation === 'publish' && (state !== 'prepared' || !prepared) || ['prepare', 'renew'].includes(operation) && ['unknown', 'pending'].includes(state);
  return <section className="preview-panel"><h2>Research graph</h2><p>Persisted example graph is not the authored draft graph. Inspecting either does not publish or automatically query a database.</p><Select label="Graph view" value={view} onChange={setView} options={[[ 'persisted', 'Persisted example inspection'], ['authored', 'Authored graph explanation'], ['publication', 'Publication preparation & outcome']]} />
    {view === 'persisted' && <><Select label="Graph inspection state" value={graphState} onChange={setGraphState} options={[[ 'example'], ['empty'], ['loading'], ['failed']]} /><Input label="Filter example graph labels" value={query} onChange={setQuery} /><p>Local label filter only; no Cypher input, database access, or implicit publication.</p>{graphState === 'example' && nodes.length ? <><table className="preview-table" aria-label="Persisted example graph"><thead><tr><th>Example node</th><th>Provenance</th></tr></thead><tbody>{nodes.map(node => <tr key={node}><td>{node}</td><td>Example persisted-version fixture; not a verified receipt</td></tr>)}</tbody></table><Select label="Inspect example node" value={selectedNode} onChange={setSelectedNode} options={[[ 'example-scene'], ['example-task'], ['example-asset']]} /><p>{selectedNode}: example-scene → has-task → example-task; example-task → uses → example-asset. Relationship layout is not physical pose.</p></> : <p role="status">Example {graphState}: no matching graph records available.</p>}<RequestReview context={context} action="read-only graph inspection" fields={{ query, graphState, selectedNode }} /></>}
    {view === 'authored' && <><h3>Authored versus persisted</h3><p>The Environment graph describes the current local specification. Unsaved edits, generated candidates and validation do not appear in the persisted research graph automatically. Save, preparation and publication are separate reviewed operations; a graph edge never proves physical success.</p><RequestReview context={context} action="inspect authored specification only" fields={{ dirty: context.dirty }} /></>}
    {view === 'publication' && <><Select label="Publication target profile" value={target} onChange={value => { setTarget(value); setConsent(false); }} options={[[ 'example-research'], ['example-sandbox']]} /><Select label="Publication example state" value={state} onChange={value => { setState(value); setConsent(false); setReconcileConsent(false); if (value === 'prepared') setPrepared({ context: { ...context }, target }); }} options={[[ 'empty'], ['prepared'], ['pending'], ['verified', 'Verified-state example (not a real receipt)'], ['unknown'], ['blocked'], ['failed']]} />
      <p>Preparation validates a saved exact version and freezes its target without writing the graph. Explicitly selecting Prepared here creates a local example preparation, not a backend reservation.</p>
      {prepared && <section className="preview-panel"><h3>Frozen preparation example</h3><p>{prepared.context.versionId ?? 'Missing version identity'} → {prepared.target}. Later selection/profile changes do not retarget this preparation.</p></section>}
      {state === 'unknown' && <p role="status">No blind retry: publication outcome is unknown. Observe exact disposition first; graph-read reconciliation is separately authorized and is not a new publish. Cross-session recovery is unsupported.</p>}
      <Select label="Publication operation" value={operation} onChange={value => { setOperation(value); setConsent(false); setReconcileConsent(false); }} options={[[ 'prepare', 'Prepare (no graph write)'], ['publish', 'Publish frozen preparation'], ['observe', 'Observe disposition (read only)'], ['reconcile', 'Reconcile graph read (explicit scope)'], ['renew', 'Review authorization renewal']]} />
      {operation === 'publish' && <Check label="Consent to publish the frozen example target" checked={consent} onChange={setConsent} />}
      {operation === 'reconcile' && <Check label="Consent to bounded graph-read reconciliation" checked={reconcileConsent} onChange={setReconcileConsent} />}
      {blocked && <p>Operation blocked: publishing requires a prepared identity; pending or unknown publication permits observation or separately reviewed reconciliation, never a fresh write.</p>}
      <RequestReview context={operation === 'prepare' ? context : prepared?.context ?? context} action={`publication ${operation}`} fields={{ operation, state, target: operation === 'prepare' ? target : prepared?.target ?? 'example-target-unresolved', consent, reconcileConsent, reservation: prepared ? 'example-reservation' : 'unavailable' }} blocked={blocked} validate={() => {
        if (operation === 'prepare' && (!context.versionId || context.dirty)) return 'Preparation requires a saved exact version; review or save dirty draft separately.';
        if (operation === 'publish' && (!prepared?.context.versionId || prepared.context.dirty)) return 'Frozen preparation lacks a saved exact version.';
        if (operation === 'publish' && JSON.stringify(prepared?.context) !== JSON.stringify(context)) return 'Frozen preparation belongs to the previous bound source; explicitly select a new Prepared example for this source before consenting.';
        if (operation === 'publish' && !consent) return 'Explicit publish consent is required for this frozen example target.';
        if (operation === 'reconcile' && (!reconcileConsent || !prepared)) return 'Reconciliation requires explicit graph-read consent and an exact retained preparation.';
        if (operation === 'renew' && state !== 'blocked') return 'Renewal review is only available for a known blocked authorization, not an unknown outcome.';
        return '';
      }} />
      <details><summary>Advanced publication identity & recovery limits</summary><p>Required runtime binding: reservation, immutable manifest, registry, revision, target profile and owner session. Readback must match the exact accepted target before a real verified badge. A missing acknowledgement is not rejection; publication failure is distinct from saving failure. Retention and cross-session renewal are not implemented in this preview.</p></details>
    </>}
  </section>;
}
function SettingsPanel({ context }: { context: PreviewContext }) {
  const [provider, setProvider] = useState('example-anthropic');
  const [model, setModel] = useState('example-balanced');
  const [temperature, setTemperature] = useState('0.2');
  const [endpoint, setEndpoint] = useState('example-managed');
  const [graph, setGraph] = useState('example-readonly');
  const [policy, setPolicy] = useState('example-gr00t');
  const [storage, setStorage] = useState('example-artifacts');
  const [readiness, setReadiness] = useState('missing');
  const [calls, setCalls] = useState('5');
  const [resource, setResource] = useState('example-single-gpu');
  return <section className="preview-panel"><h2>Settings & readiness</h2><p>Nonsecret configuration concepts only. No credential entry, retention, provider ping or profile discovery. Example profiles are not operator approvals.</p><div className="preview-grid"><Select label="Provider" value={provider} onChange={value => { setProvider(value); setModel('example-balanced'); }} options={[[ 'example-anthropic', 'Anthropic (example)'], ['example-openai', 'OpenAI (example)'], ['example-managed', 'Managed compatible provider (example)']]} /><Select label="Model" value={model} onChange={setModel} options={[[ 'example-balanced', 'Example balanced model (not a real model ID)'], ['example-small', 'Example small model (not a real model ID)']]} /><Input label="Temperature" value={temperature} onChange={setTemperature} min={0} max={2} /><Select label="Endpoint profile" value={endpoint} onChange={setEndpoint} options={[[ 'example-managed'], ['example-local', 'Example operator-managed local endpoint']]} /></div>
    <h3>Independent readiness dimensions</h3><Select label="Readiness example" value={readiness} onChange={setReadiness} options={[[ 'missing', 'Missing configuration'], ['configured', 'Configured example (not authenticated)'], ['blocked', 'Adapter unavailable'], ['session-expired', 'Session expired'], ['storage-unavailable', 'Storage unavailable']]} /><p>Configuration: {readiness === 'configured' ? 'example fields selected, not runtime-validated' : readiness}.</p><p>Authentication: not verified. A profile name does not prove valid credentials.</p><p>Inference: not tested. Configuration and authentication do not prove a model call succeeded.</p>
    {readiness === 'session-expired' && <p role="status">Session expired: reconnect and reauthorize exact scopes in the future runtime. Old requests cannot silently adopt a replacement session.</p>}
    {readiness === 'storage-unavailable' && <p role="status">Storage unavailable: no durable retention is claimed; unknown requests require observation, not a new submission.</p>}
    <h3>Approved-profile concepts</h3><div className="preview-grid"><Select label="Graph profile" value={graph} onChange={setGraph} options={[[ 'example-readonly'], ['example-publisher', 'Example explicit publication scope']]} /><Select label="Policy profile" value={policy} onChange={setPolicy} options={[[ 'example-gr00t'], ['example-openpi']]} /><Select label="Storage profile" value={storage} onChange={setStorage} options={[[ 'example-artifacts'], ['example-readonly-archive']]} /></div><p>Policy checkpoint/server identity: missing — not verified. Storage roots and graph endpoints are operator-managed; arbitrary host paths and URLs are not accepted.</p>
    <details open><summary>Owner, resource & budget review</summary><div className="preview-grid"><Select label="Resource profile" value={resource} onChange={setResource} options={[[ 'example-single-gpu'], ['example-cpu-inspection']]} /><Input label="Default model call ceiling" value={calls} onChange={setCalls} min={1} max={20} /></div><p>Owner: example-session only. GPU/display readiness, lease availability, disk capacity and policy compatibility are unknown. The call ceiling is a requested limit, not usage statistics. Runtime admission must check all prerequisites before any work.</p></details>
    <details><summary>Advanced key lifecycle & profile restrictions</summary><p>Keys belong in a future explicitly authorized credential flow, never this preview. Configuration, authentication and inference have separate statuses. Temporary access may expire before jobs; forgetting access does not prove already-authorized work stopped. No browser shell, raw secrets, environment overrides, profile file loading or functioning renewal is available.</p></details>
    <RequestReview context={context} action="review nonsecret configuration" fields={{ provider, model, temperature, endpoint, graph, policy, storage, readiness, calls, resource }} validate={() => !/^\d+(\.\d+)?$/.test(temperature) || Number(temperature) < 0 || Number(temperature) > 2 ? 'Temperature must be a finite number from 0 to 2.' : !integer(calls, 1, 20) ? 'Default model call ceiling must be 1–20.' : ''} />
  </section>;
}
export function WorkflowPanels({ section, context: selection }: { section: Section; context: PreviewContext }) {
  // The app retains each visited form mounted, including during ordinary navigation.
  const [context, setContext] = useState(() => ({ ...selection }));
  const [retainFor, setRetainFor] = useState<string | null>(null);
  const selectionKey = JSON.stringify(selection);
  const changed = JSON.stringify(context) !== selectionKey;
  const canRebind = changed && !!selection.familyId && !!selection.versionId && !selection.dirty;
  if (section === 'runs') return <RunsPanel />;
  return <>
    <section className="preview-panel" aria-label="Workflow source binding">
      <p aria-label="Bound workflow source">Bound workflow source: {context.familyId ?? 'No family'} / {context.versionId ?? 'No saved version'} · {!savedSource(context) ? 'Unresolved source — draft not captured' : 'Saved example revision only'}</p>
      <p aria-label="Current workflow selection">Current selection: {selection.familyId ?? 'No family'} / {selection.versionId ?? 'No saved version'} · {selection.dirty ? 'Dirty draft — not captured' : 'No draft content captured'}</p>
      <p>Forms keep their original bound source and options through navigation and selection changes. Draft content and exact draft identity are not captured; a dirty flag is not a revision. Already reviewed requests stay frozen.</p>
      {changed && <p>Selection differs from the bound source. Rebinding changes this form only, retains options with your agreement, and requires fresh target-specific consent. It never retargets an existing review or publication preparation.</p>}
      <Check label="Keep form options for the selected saved version; review all target-specific consent again" checked={retainFor === selectionKey} onChange={value => setRetainFor(value ? selectionKey : null)} />
      <button type="button" disabled={!canRebind || retainFor !== selectionKey} onClick={() => { setContext({ ...selection }); setRetainFor(null); }}>Rebind form to selected version</button>
      {!selection.versionId || selection.dirty ? <p>Select a clean saved example version before rebinding. Unsaved or dirty drafts remain unresolved, not captured.</p> : null}
    </section>
    {section === 'settings' && <SettingsPanel context={context} />}
    {section === 'graph' && <GraphPanel context={context} />}

    {section === 'experiments' && <ExperimentsPanel context={context} />}
    {section === 'build' && <BuildPanel context={context} />}
    {section === 'improve' && <ImprovePanel context={context} />}
  </>;
}
