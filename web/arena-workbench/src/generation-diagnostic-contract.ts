const codes = ['provider_authentication', 'provider_permission', 'provider_rate_limit', 'provider_model_unavailable', 'provider_request_rejected', 'provider_schema_rejected', 'provider_parameter_unsupported', 'provider_schema_min_items_unsupported', 'provider_schema_max_items_unsupported', 'provider_schema_prefix_items_unsupported', 'provider_timeout', 'provider_connection', 'dependency_unavailable', 'required_retrieval_unavailable', 'invalid_specification', 'worker_protocol', 'worker_exited', 'worker_timeout', 'internal_error'] as const;
const stages = ['worker_starting', 'agent_initializing', 'catalogues_loading', 'graph_priors_loading', 'spec_inference', 'prim_paths_resolving', 'spatial_grounding', 'validation_iteration_1', 'validation_iteration_2', 'generation_completed', 'result_validating'];
export interface GenerationDiagnosticRecord {schema_version: 1; code: typeof codes[number]; stage: string}
/** Pure decoder shared by HTTP, SharedWorker and rendering boundaries. */
export function isGenerationDiagnostic(value: unknown): value is GenerationDiagnosticRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return Object.keys(record).length === 3 && record.schema_version === 1
    && typeof record.code === 'string' && (codes as readonly string[]).includes(record.code)
    && typeof record.stage === 'string' && stages.includes(record.stage);
}
