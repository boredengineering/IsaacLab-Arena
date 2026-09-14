import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { GenerationEvidence } from './generation-evidence';

it('shows observed timing and bounded effective settings without inventing missing observations', () => {
  const { rerender } = render(<GenerationEvidence value={{ prior_snapshot: {
    status: 'empty', timing: { source: 'local_monotonic', elapsed_seconds: 0.25 },
    effective_settings: { limit: 2, min_success_rate: 0, min_episodes: 1, query_timeout_seconds: 5, connection_timeout_seconds: null },
  } }} />);
  expect(screen.getByText('Observed retrieval time: 0.25 seconds')).toBeInTheDocument();
  expect(screen.getByText('Prior limit: 2')).toBeInTheDocument();
  expect(screen.getByText('Connection timeout (seconds): Not observed')).toBeInTheDocument();
  rerender(<GenerationEvidence value={{ prior_snapshot: { status: 'not_requested', timing: { source: 'not_started', elapsed_seconds: null } } }} />);
  expect(screen.getByText('Retrieval was not started.')).toBeInTheDocument();
  rerender(<GenerationEvidence value={{ prior_snapshot: { status: 'unavailable', warnings: ['retrieval_failed'], timing: { source: 'unavailable', elapsed_seconds: null } } }} />);
  expect(screen.getByText('Retrieval timing not recorded.')).toBeInTheDocument();
  expect(screen.queryByText('Retrieval was not started.')).not.toBeInTheDocument();
});

it('distinguishes unavailable retrieval from no eligible priors and legacy absence', () => {
  const { rerender } = render(<GenerationEvidence value={{ prior_snapshot: { status: 'unavailable', warnings: ['unconfigured'], priors: [] } }} />);
  expect(screen.getByText('Retrieval unavailable')).toBeInTheDocument();
  rerender(<GenerationEvidence value={{ prior_snapshot: { status: 'empty', priors: [] } }} />);
  expect(screen.getByText('No eligible priors')).toBeInTheDocument();
  rerender(<GenerationEvidence value={{}} />);
  expect(screen.getByText(/Retrieval evidence was not recorded/)).toBeInTheDocument();
});

it('shows exact provenance without turning structural precedent into measured success', () => {
  render(<GenerationEvidence value={{ catalogue_sha256: 'catalogue-digest', prior_snapshot: {
    status: 'structural', derived_filters: { emb_filter: 'droid', fixture_filter: 'table' },
    priors: [{ name: '<img src=x onerror=alert(1)>', evidence: 'unevaluated', evaluation_id: null, policy_identity: null }],
    exact_context: '<script>not executable</script>', context_sha256: 'context-digest', warnings: [],
  } }} />);
  expect(screen.getByText('Structural precedent — not measured policy success')).toBeInTheDocument();
  expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
  expect(screen.getByText('context-digest')).toBeInTheDocument();
  expect(document.querySelector('script,img')).toBeNull();
  expect(screen.getByText(/Unknown/)).toBeInTheDocument();
});
