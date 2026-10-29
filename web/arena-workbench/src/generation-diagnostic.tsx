import { isGenerationDiagnostic } from './generation-diagnostic-contract';
export { isGenerationDiagnostic } from './generation-diagnostic-contract';

const guidance = {
  provider_authentication: ['Provider authentication was rejected.', 'Check the selected provider and key in Temporary provider settings.'],
  provider_permission: ['The provider denied access.', 'Check account permissions and access to the selected model.'],
  provider_rate_limit: ['The provider reported a rate or quota limit.', 'Check provider quota and billing before explicitly submitting another attempt.'],
  provider_model_unavailable: ['The provider could not find the requested model or endpoint.', 'Check the exact model ID for the selected provider.'],
  provider_request_rejected: ['The provider rejected the request.', 'The exact rejection reason is unknown in this record. Raw provider details were not retained. Check model compatibility, request parameters and structured-output schema before considering another explicit attempt.'],
  provider_schema_rejected: ['The provider rejected the structured-output JSON schema.', 'The exact schema defect was not classified. Review the generated wire schema against the selected model’s supported subset; this is not evidence that the scene content is invalid.'],
  provider_parameter_unsupported: ['The provider rejected an unsupported request parameter or value.', 'The exact parameter and value were not classified. Review the harness request-policy profile for the selected model; changing the scene prompt alone does not fix request parameters.'],
  provider_schema_min_items_unsupported: ['The provider rejected the JSON schema keyword minItems.', 'Review the structured-output adapter for the selected model, preserving array-length validation rather than silently dropping the constraint.'],
  provider_schema_max_items_unsupported: ['The provider rejected the JSON schema keyword maxItems.', 'Review the structured-output adapter for the selected model, preserving array-length validation rather than silently dropping the constraint.'],
  provider_schema_prefix_items_unsupported: ['The provider rejected the JSON schema keyword prefixItems.', 'Review the structured-output adapter for the selected model, preserving tuple semantics rather than silently dropping positional constraints.'],
  provider_timeout: ['The provider request timed out.', 'Inspect provider-side history before deciding whether to submit another attempt.'],
  provider_connection: ['The provider connection failed.', 'Check endpoint connectivity and TLS from the Arena runtime.'],
  dependency_unavailable: ['A generation dependency is unavailable.', 'Check the installed runtime dependencies; a frontend build does not verify Python packages.'],
  required_retrieval_unavailable: ['Required Graph-RAG retrieval is unavailable.', 'Check the explicit Neo4j configuration and database readiness. Do not enable fallback to claim a Graph-RAG experiment.'],
  invalid_specification: ['Generation did not produce an accepted Arena specification.', 'Review the prompt and supported catalogue; no valid candidate was accepted.'],
  worker_protocol: ['The worker response could not be verified.', 'Inspect the runtime integration before another attempt.'],
  worker_exited: ['The generation worker exited without an accepted candidate.', 'Check runtime dependencies and the last reported stage.'],
  worker_timeout: ['The generation worker exceeded its time budget.', 'Review the last reported stage and provider history before another attempt.'],
  internal_error: ['The generation worker reported an internal failure.', 'Review runtime integration at the reported stage; raw provider data is intentionally withheld.'],
} as const;

/** Diagnostic evidence never changes candidate acceptance or external-effect uncertainty. */
export function GenerationDiagnostic({value}: {value: unknown}) {
  if (!isGenerationDiagnostic(value)) return null;
  const [message, action] = guidance[value.code];
  return <section className="notice warning" aria-label="Generation diagnostic">
    <h3>Generation diagnostic</h3>
    <p>{message}</p><p>{action}</p>
    <dl><dt>Last reported stage</dt><dd><code>{value.stage}</code></dd><dt>Diagnostic code</dt><dd><code>{value.code}</code></dd></dl>
    <p>This diagnostic does not prove that the provider performed no work. It does not authorize a retry or establish a successful result.</p>
  </section>;
}
