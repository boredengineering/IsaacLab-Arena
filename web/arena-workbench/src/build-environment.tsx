import type { Job } from './contracts';
import type { BuildResult } from './editor-contracts';
import { EditorJobProgress, useEditorJob } from './editor-jobs';

const hash = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
function fixedProfile(value: Record<string, unknown>) {
  return value.headless === true && value.num_envs === 1 && value.num_steps === 20 && value.policy === 'zero_action';
}
/** Completion is evidence for this frozen job/profile, never a policy evaluation. */
export function parseBuildResult(job: Job): BuildResult | null {
  const result = job.result;
  const inputs = job.inputs;
  if (job.kind !== 'build' || job.status !== 'succeeded' || !result || result.schema_version !== 1
    || result.completed !== true || !fixedProfile(result) || !fixedProfile(inputs)
    || !hash(result.input_hash) || !hash(result.canonical_hash)
    || result.input_hash !== inputs.input_hash || result.canonical_hash !== inputs.canonical_hash
    || typeof inputs.yaml_text !== 'string' || !inputs.yaml_text.trim()
    || !(inputs.document_id === null || typeof inputs.document_id === 'string')) return null;
  return { schema_version: 1, input_hash: result.input_hash, canonical_hash: result.canonical_hash,
    headless: true, num_envs: 1, num_steps: 20, policy: 'zero_action', completed: true };
}

export function BuildOutcome({ job }: { job?: Job }) {
  if (!job || job.kind !== 'build') return null;
  const result = parseBuildResult(job);
  if (!result) return job.status === 'succeeded'
    ? <p className="notice warning">Build completion is unverified: the result is missing, malformed or does not match the frozen inputs.</p>
    : null;
  return <section aria-label="Build result">
    <h3>Build completed</h3>
    <p>Completed 20 zero-action steps in one headless environment. This is not policy success or physics proof.</p>
    <dl>
      <dt>Input hash</dt><dd><code>{result.input_hash}</code></dd>
      <dt>Canonical hash</dt><dd><code>{result.canonical_hash}</code></dd>
    </dl>
    <p className="hint">Result belongs to this job’s frozen inputs, not subsequent draft edits. No generation or publication was performed.</p>
  </section>;
}

export function BuildControls({ draft, documentId, enabled, available, canLaunch, canDispatch }: {
  draft: string;
  documentId?: string;
  enabled: boolean;
  available: boolean;
  canLaunch: () => boolean;
  canDispatch: () => boolean;
}) {
  const controller = useEditorJob('build');
  const retry = !!controller.retained && !controller.job;
  const allowed = available && (retry || enabled);
  return <section aria-label="Build environment">
    <h2>Build environment</h2>
    <p>Runs 20 zero-action simulation steps. Fixed profile: headless, 1 environment, 20 steps, zero_action policy.</p>
    <p className="notice warning">Simulation effects: this starts the simulator and advances the scene; it is not a zero-step check. It does not regenerate YAML or publish anything.</p>
    <p className="hint">Adapter support does not guarantee GPU or simulator readiness.</p>
    <button type="button" disabled={!allowed || controller.busy} onClick={() => {
      if (!allowed || controller.busy || !canDispatch() || (!retry && !canLaunch())) return;
      // Capture the validated click's source before the job controller awaits activity.
      controller.submit.mutate({ yaml_text: draft, ...(documentId ? { document_id: documentId } : {}) }, canDispatch);
    }}>{controller.submit.isPending ? 'Submitting build…' : retry ? 'Retry build request' : 'Build environment'}</button>
    {!available && <p className="hint">Build unavailable: an active session and advertised Build adapter are required.</p>}
    {available && !enabled && !retry && <p className="hint">Validate the current draft before building.</p>}
    <EditorJobProgress controller={controller} />
    <BuildOutcome job={controller.job} />
  </section>;
}
