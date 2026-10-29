const object = (value: unknown): Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown, limit = 4096) => typeof value === 'string' && value ? value.slice(0, limit) : 'Unknown';
const nonnegative = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const settingLabels = [
  ['limit', 'Prior limit'], ['min_success_rate', 'Minimum success ratio'], ['min_episodes', 'Minimum episodes'],
  ['query_timeout_seconds', 'Query timeout (seconds)'], ['connection_timeout_seconds', 'Connection timeout (seconds)'],
  ['connection_acquisition_timeout_seconds', 'Connection acquisition timeout (seconds)'],
  ['max_transaction_retry_time_seconds', 'Transaction retry budget (seconds)'],
] as const;
const labels: Record<string, string> = {
  measured: 'Measured priors — not proof of this new task’s success',
  structural: 'Structural precedent — not measured policy success',
  empty: 'No eligible priors',
  unavailable: 'Retrieval unavailable',
  not_requested: 'Retrieval not requested for refinement',
};

/** Read-only, bounded evidence display; never infers provenance from a later graph query. */
export function GenerationEvidence({ value }: { value: unknown }) {
  const result = object(value);
  const snapshot = object(result.prior_snapshot);
  if (Object.keys(snapshot).length === 0) return <p className="muted">Retrieval evidence was not recorded for this job.</p>;
  const status = typeof snapshot.status === 'string' ? snapshot.status : '';
  const filters = object(snapshot.derived_filters);
  const priors = Array.isArray(snapshot.priors) ? snapshot.priors : [];
  const warnings = Array.isArray(snapshot.warnings) ? snapshot.warnings : [];
  const timing = object(snapshot.timing), settings = object(snapshot.effective_settings);
  return <section aria-label="Generation evidence">
    <h4>Last completed generation evidence</h4>
    <p>{Object.hasOwn(labels, status) ? labels[status] : 'Unrecognized retrieval evidence'}</p>
    <dl>
      <dt>Context digest</dt><dd style={{ overflowWrap: 'anywhere' }}>{text(snapshot.context_sha256, 128)}</dd>
      <dt>Catalogue digest</dt><dd style={{ overflowWrap: 'anywhere' }}>{text(result.catalogue_sha256, 128)}</dd>
      <dt>Retrieval filters</dt><dd>{text(filters.emb_filter, 128)} / {text(filters.fixture_filter, 128)}</dd>
    </dl>
    <p>{timing.source === 'local_monotonic' && nonnegative(timing.elapsed_seconds)
      ? `Observed retrieval time: ${timing.elapsed_seconds} seconds`
      : timing.source === 'not_started' && timing.elapsed_seconds === null ? 'Retrieval was not started.' : 'Retrieval timing not recorded.'}</p>
    {Object.keys(settings).length > 0 && <details>
      <summary>Effective retrieval settings</summary>
      <ul>{settingLabels.map(([key, label]) => <li key={key}>{label}: {nonnegative(settings[key]) ? String(settings[key]) : 'Not observed'}</li>)}</ul>
    </details>}
    <ul>{priors.slice(0, 5).map((raw, index) => {
      const prior = object(raw);
      const measured = prior.evidence === 'measured';
      const rate = typeof prior.success_rate === 'number' && Number.isFinite(prior.success_rate) && prior.success_rate >= 0 && prior.success_rate <= 1 ? prior.success_rate : 'Unknown';
      const episodes = typeof prior.episodes === 'number' && Number.isSafeInteger(prior.episodes) && prior.episodes > 0 ? prior.episodes : 'Unknown';
      return <li key={index}>
        <strong>{text(prior.name)}</strong>
        <p>{measured ? `Reported success ratio: ${rate}; completed episodes: ${episodes}` : 'No qualifying measured policy evidence'}</p>
        <p>Graph version: {text(prior.graph_version)}; Evaluation: {text(prior.evaluation_id)}; Policy: {text(prior.policy_identity)}; Checkpoint: {text(prior.checkpoint_identity)}</p>
      </li>;
    })}</ul>
    {priors.length > 5 && <p>Additional prior entries omitted from this bounded display.</p>}
    {warnings.length > 0 && <p>Retrieval warnings: {warnings.slice(0, 8).map(w => text(w, 128)).join(', ')}</p>}
    {typeof snapshot.exact_context === 'string' && snapshot.exact_context && <details>
      <summary>Context supplied to generation</summary>
      <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 240, overflow: 'auto' }}>{snapshot.exact_context.slice(0, 32768)}</pre>
      {snapshot.exact_context.length > 32768 && <p>Context display truncated.</p>}
    </details>}
  </section>;
}
