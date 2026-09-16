import { useLayoutEffect, useRef, useState } from 'react';
import type { ApiClient } from './api';
import type { Validation } from './editor-contracts';
import { positionEditEligibility } from './position-edit-eligibility';
import { proposeRootPositionEdit, type RootPositionEditResult } from './authored-yaml-edit';

/** Actual Editor draft and returned frozen view, never validation.spec serialization. */
export interface PositionEditBinding {
  api: ApiClient; draft: string; documentId: string; sourceHash: string;
  bindingKey: string; optionsKey: string; active: boolean; validationReady: boolean;
  /** Checks the owning Editor's live session/source/activity epoch before effects. */
  isCurrent: () => boolean;
  /** Local draft replacement only; caller invalidates and freshly validates it. */
  onApply: (candidate: string) => boolean;
}
type Props = { binding: PositionEditBinding; validation: Validation | null; selectedId: string };
type Proposal = Extract<RootPositionEditResult, {ok: true}>;
type Review = { proposal: Proposal; sequence: number; status: 'pending' | 'valid' | 'failed' | 'applied'; findings: string[] };
async function sha256(text: string) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))), b => b.toString(16).padStart(2, '0')).join('');
}
export function ReviewedPositionEdit(props: Props) {
  const {binding: b, validation, selectedId} = props;
  const identity = [b.api, b.api.sessionGeneration, b.draft, b.documentId, b.sourceHash, b.bindingKey, b.optionsKey, b.active, b.validationReady, validation, selectedId];
  const scope = useRef({identity, epoch: 0});
  if (identity.some((v, i) => v !== scope.current.identity[i])) scope.current = {identity, epoch: scope.current.epoch + 1};
  const epoch = scope.current.epoch;
  return <BoundPositionEdit key={epoch} {...props} ownsScope={() => scope.current.epoch === epoch} />;
}
function BoundPositionEdit({binding: b, validation, selectedId, ownsScope}: Props & {ownsScope: () => boolean}) {
  const eligibility = positionEditEligibility(b.draft, validation, selectedId);
  const [axis, setAxis] = useState<0 | 1 | 2>(0);
  const [value, setValue] = useState(eligibility.ok ? String(eligibility.position[0]) : '');
  const [review, setReview] = useState<Review | null>(null);
  const [consent, setConsent] = useState(false);
  const consentEpoch = useRef(0);
  const renderedConsentEpoch = consentEpoch.current;
  const [error, setError] = useState('');
  const serial = useRef(0);
  const renderedSerial = serial.current;
  const mounted = useRef(false);
  useLayoutEffect(() => { mounted.current = true; return () => { mounted.current = false; serial.current++; }; }, []);
  const generation = useRef(b.api.sessionGeneration).current;
  const current = () => mounted.current && ownsScope() && b.active && b.validationReady && !!b.api.session && b.api.sessionGeneration === generation && b.isCurrent();
  const bound = !!b.documentId && /^[a-f0-9]{64}$/.test(b.sourceHash);
  const number = value.trim() ? Number(value) : NaN;
  const editable = eligibility.ok && bound && b.active && b.validationReady;
  function retireOptions() { serial.current++; setReview(null); setConsent(false); setError(''); }
  async function propose() {
    if (!current() || serial.current !== renderedSerial || !editable || !Number.isFinite(number) || !eligibility.ok) return;
    const proposal = proposeRootPositionEdit({draft: b.draft, role: eligibility.role, nodeId: selectedId, axis, value: number});
    retireOptions();
    if (!proposal.ok) { setError(`No proposal: ${proposal.reason}.`); return; }
    const sequence = serial.current;
    const owns = () => current() && serial.current === sequence;
    setReview({proposal, sequence, status: 'pending', findings: []});
    try {
      const originalHash = await sha256(b.draft);
      if (!owns()) return;
      if (originalHash !== validation?.source_hash) throw new Error('Current validation does not match the exact root draft.');
      const candidateHash = await sha256(proposal.candidate);
      if (!owns()) return;
      const result = await b.api.mutate<Validation>('/editor/validate', {yaml_text: proposal.candidate, document_id: b.documentId});
      if (!owns()) return;
      if (!result || result.source_hash !== candidateHash || !Array.isArray(result.warnings) || !Array.isArray(result.errors) || ![...result.warnings, ...result.errors].every(v => typeof v === 'string')) throw new Error('Candidate response does not match the exact source.');
      const checked = positionEditEligibility(proposal.candidate, result, selectedId);
      setReview({proposal, sequence, status: checked.ok ? 'valid' : 'failed', findings: [...result.errors, ...result.warnings, ...(!checked.ok ? [checked.reason] : [])]});
    } catch {
      if (owns()) setReview({proposal, sequence, status: 'failed', findings: ['Candidate validation failed or mismatched; nothing was applied. Revalidate explicitly.']});
    }
  }
  function apply() {
    if (!current() || !editable || !consent || consentEpoch.current !== renderedConsentEpoch || review?.status !== 'valid' || review.sequence !== serial.current) return;
    // Retire synchronously before calling out; double clicks and retained callbacks
    // cannot reapply. Recheck original eligibility, not just a success badge.
    if (!positionEditEligibility(b.draft, validation, selectedId).ok) return;
    serial.current++;
    setConsent(false);
    setReview({...review, status: 'applied'});
    if (!b.onApply(review.proposal.candidate)) setError('The editor binding retired; nothing was applied.');
  }
  return <section className="reviewed-position-edit" aria-label="Reviewed position edit">
    <h4>Root XYZ position · reviewed edit</h4>
    <p>Descriptor v1: background / table, explicit identity rotation, no incident constraints or reference children. Authored environment-frame meters, not runtime placement. Background object_min_z does not move with the table. Quaternion, scale and included-field edits are unsupported.</p>
    {!editable && <p role="status">{!eligibility.ok ? eligibility.reason : 'An active, frozen source document is required.'} Use the raw specification instead.</p>}
    {editable && <>
      <label>Position axis<select aria-label="Position axis" value={axis} onChange={e => {retireOptions(); const next = Number(e.target.value) as 0 | 1 | 2; setAxis(next); setValue(String(eligibility.position[next]));}}>
        <option value="0">X</option><option value="1">Y</option><option value="2">Z</option>
      </select></label>
      <label>Proposed coordinate (m)<input aria-label="Proposed coordinate (m)" type="text" inputMode="decimal" value={value} onChange={e => {retireOptions(); setValue(e.target.value);}} /></label>
      <button type="button" disabled={!Number.isFinite(number) || review?.status === 'pending'} onClick={() => void propose()}>Validate position proposal</button>
    </>}
    {error && <p role="alert">{error}</p>}
    {review && <>
      <section aria-label="Exact source diff"><h4>Exact source diff</h4>
        <p>{selectedId} · params.initial_pose.position_xyz[{axis}] · {String(review.proposal.before)} → {String(review.proposal.after)}. Only this numeric token changes; all other raw bytes are preserved.</p>
        <details open><summary>Original root YAML</summary><pre aria-label="Original root YAML">{b.draft}</pre></details>
        <details open><summary>Candidate root YAML</summary><pre aria-label="Candidate root YAML">{review.proposal.candidate}</pre></details>
      </section>
      <section aria-label="Candidate validation"><h4>Candidate validation · separate from current draft</h4>
        <p role="status">{review.status === 'valid' ? 'Candidate schema valid · not runtime-validated' : review.status === 'pending' ? 'Candidate validation pending' : review.status === 'applied' ? 'Applied locally; fresh draft validation required' : 'Candidate validation failed'}</p>
        {review.findings.map((finding, i) => <p key={i}>{finding}</p>)}
      </section>
      <label><input type="checkbox" checked={consent} disabled={review.status !== 'valid'} onChange={e => {
        if (!current() || review.status !== 'valid' || review.sequence !== serial.current || consentEpoch.current !== renderedConsentEpoch) return;
        consentEpoch.current++;
        setConsent(e.target.checked);
      }} />I reviewed this exact source diff</label>
      <button type="button" disabled={!editable || !consent || review.status !== 'valid'} onClick={apply}>Apply reviewed position</button>
      <p>Apply replaces the local draft and requires fresh validation. It does not save, publish or run physics, and does not itself submit a render. Existing automatic-preview consent is unchanged: if already enabled, it may render the changed draft after fresh validation within the existing job budget. Turn automatic previews off before Apply to prevent that work.</p>
    </>}
  </section>;
}
