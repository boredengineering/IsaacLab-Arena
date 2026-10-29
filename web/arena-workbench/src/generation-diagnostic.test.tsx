import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { GenerationDiagnostic, isGenerationDiagnostic } from './generation-diagnostic';

it('displays static provider guidance while preserving unknown execution outcome', () => {
  render(<GenerationDiagnostic value={{schema_version: 1, code: 'provider_authentication', stage: 'agent_initializing'}} />);
  expect(screen.getByText('Provider authentication was rejected.')).toBeVisible();
  expect(screen.getByText(/does not prove that the provider performed no work/)).toBeVisible();
  expect(screen.getByText('agent_initializing')).toBeVisible();
});

it.each([
  ['provider_schema_rejected', 'The provider rejected the structured-output JSON schema.', /exact schema defect was not classified/i],
  ['provider_parameter_unsupported', 'The provider rejected an unsupported request parameter or value.', /exact parameter and value were not classified/i],
  ['provider_schema_min_items_unsupported', 'The provider rejected the JSON schema keyword minItems.', /preserving array-length validation/i],
  ['provider_schema_max_items_unsupported', 'The provider rejected the JSON schema keyword maxItems.', /preserving array-length validation/i],
  ['provider_schema_prefix_items_unsupported', 'The provider rejected the JSON schema keyword prefixItems.', /preserving tuple semantics/i],
  ['provider_model_unavailable', 'The provider could not find the requested model or endpoint.', /exact model ID/i],
  ['provider_request_rejected', 'The provider rejected the request.', /exact rejection reason is unknown/i],
])('explains %s without granting execution or retry authority', (code, message, action) => {
  const value = {schema_version: 1, code, stage: 'spec_inference'};
  expect(isGenerationDiagnostic(value)).toBe(true);
  render(<GenerationDiagnostic value={value} />);
  expect(screen.getByText(message)).toBeVisible();
  expect(screen.getByText(action)).toBeVisible();
  expect(screen.getByText(/does not authorize a retry or establish a successful result/)).toBeVisible();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

it('retains honest legacy generic rejection without inventing schema evidence', () => {
  render(<GenerationDiagnostic value={{schema_version: 1, code: 'provider_request_rejected', stage: 'spec_inference'}} />);
  expect(screen.getByText(/exact rejection reason is unknown/i)).toBeVisible();
  expect(screen.queryByText('The provider rejected the structured-output JSON schema.')).not.toBeInTheDocument();
});

it.each([
  {schema_version: 1, code: 'provider_schema_min_items_unsupported-synthetic-private-marker', stage: 'spec_inference'},
  {schema_version: 1, code: 'provider_schema_rejected', stage: 'spec_inference', message: 'synthetic-private-marker'},
  {schema_version: 2, code: 'provider_schema_rejected', stage: 'spec_inference'},
  {schema_version: 1, code: 'provider_authentication', stage: 'synthetic-private-marker'},
  {schema_version: 1, code: 'synthetic-private-marker', stage: 'agent_initializing'},
  {schema_version: 1, code: 'provider_authentication', stage: 'agent_initializing', raw: 'synthetic-private-marker'},
  {schema_version: 1, code: ['provider_authentication'], stage: 'agent_initializing'},
])('rejects unsupported diagnostic fields rather than rendering raw data', value => {
  expect(isGenerationDiagnostic(value)).toBe(false);
  const {container} = render(<GenerationDiagnostic value={value} />);
  expect(container).toBeEmptyDOMElement();
});
