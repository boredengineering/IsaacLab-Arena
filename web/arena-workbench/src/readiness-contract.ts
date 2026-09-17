export type ReadinessWorkflow = 'agentic_generation' | 'a2_gr00t' | 'graph_generation' | 'build';
export const READINESS_CHECKS = ['api_contract', 'runtime', 'generation_model', 'graph', 'policy_protocol', 'policy_model', 'policy_transport', 'gpu'] as const;
// Exact static readiness.READINESS_CODES = RESOURCE_CODES + PROVIDER_CODES + local codes.
export const READINESS_CODES = [
  'resource_unknown', 'resource_headroom_observed', 'resource_lease_busy', 'resource_insufficient',
  'resource_device_changed', 'resource_hidden', 'resource_ambiguous',
  'generation_model_readable', 'generation_provider_unsupported', 'generation_provider_unavailable',
  'generation_authentication_failed', 'generation_permission_denied', 'generation_model_missing',
  'generation_rate_limited', 'generation_redirect_refused', 'generation_model_mismatch',
  'generation_metadata_invalid', 'generation_check_timeout',
  'not_required', 'not_checked', 'api_contract_available', 'api_contract_unavailable',
  'runtime_not_checked', 'runtime_available', 'runtime_unavailable', 'generation_not_configured',
  'generation_configuration_only', 'graph_not_configured', 'graph_invalid_configuration', 'graph_not_checked',
  'graph_retrieval_measured', 'graph_retrieval_structural', 'graph_retrieval_empty', 'graph_retrieval_unavailable',
  'configuration_changed', 'check_timeout', 'policy_protocol_available', 'policy_protocol_unavailable',
  'policy_modality_mismatch', 'policy_expectation_missing', 'policy_model_verified', 'policy_model_mismatch',
  'policy_metadata_unavailable', 'policy_transport_unverified', 'policy_transport_verified',
  'policy_instance_mismatch', 'openpi_verification_unsupported',
] as const;
export type ReadinessCheck = typeof READINESS_CHECKS[number];
export type ReadinessCode = typeof READINESS_CODES[number];
export interface ReadinessV2 {
  schema_version: 2;
  workflow: ReadinessWorkflow;
  checked_at: number | null;
  checks: {id: ReadinessCheck; status: 'passed' | 'not_checked' | 'unavailable' | 'mismatch' | 'blocked' | 'not_required'; code: ReadinessCode; required: boolean}[];
  policy: {profile: 'gr00t-droid'; expected_checkpoint: 'nvidia/GR00T-N1.6-DROID';
    instance_id: string | null; checkpoint_sha256: string | null; config_sha256: string | null;
    serializer_sha256: string | null; modalities_sha256: string | null; inference: 'not_run'} | null;
  ready: boolean;
}
function exact(value: unknown, keys: string[]): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
}
type ReadinessStatus = ReadinessV2['checks'][number]['status'];
// Public emissions from readiness.metadata_v2/check_v2 and the validated worker
// probes. A code's prefix (or membership in READINESS_CODES) is not a status grant.
const statusCodes: Record<ReadinessCheck, Partial<Record<ReadinessStatus, readonly ReadinessCode[]>>> = {
  api_contract: {passed: ['api_contract_available'], unavailable: ['api_contract_unavailable']},
  runtime: {not_checked: ['runtime_not_checked'], passed: ['runtime_available'], unavailable: ['runtime_unavailable']},
  generation_model: {
    not_required: ['not_required'],
    not_checked: ['generation_configuration_only', 'generation_not_configured'],
    passed: ['generation_model_readable'],
    unavailable: ['generation_not_configured', 'generation_provider_unsupported', 'generation_provider_unavailable',
      'generation_authentication_failed', 'generation_permission_denied', 'generation_model_missing',
      'generation_rate_limited', 'generation_redirect_refused', 'generation_model_mismatch',
      'generation_metadata_invalid', 'generation_check_timeout', 'configuration_changed'],
  },
  graph: {
    not_required: ['not_required'],
    not_checked: ['graph_not_configured', 'graph_invalid_configuration', 'graph_not_checked'],
    blocked: ['graph_invalid_configuration'], // Early return before the worker or checked_at.
    passed: ['graph_retrieval_measured', 'graph_retrieval_structural', 'graph_retrieval_empty'],
    unavailable: ['graph_not_configured', 'graph_retrieval_unavailable', 'configuration_changed'],
  },
  // Generic not_checked survives metadata and whole-worker failure only for policy.
  policy_protocol: {not_required: ['not_required'], not_checked: ['not_checked'],
    passed: ['policy_protocol_available'], unavailable: ['policy_protocol_unavailable'], mismatch: ['policy_modality_mismatch']},
  policy_model: {not_required: ['not_required'], not_checked: ['not_checked', 'policy_expectation_missing'],
    passed: ['policy_model_verified'], unavailable: ['policy_metadata_unavailable'],
    mismatch: ['policy_modality_mismatch', 'policy_model_mismatch', 'policy_instance_mismatch', 'configuration_changed']},
  policy_transport: {not_required: ['not_required'], not_checked: ['not_checked', 'policy_transport_unverified'],
    passed: ['policy_transport_verified']},
  gpu: {not_required: ['not_required'], not_checked: ['resource_unknown'], passed: ['resource_headroom_observed'],
    blocked: ['resource_unknown', 'resource_lease_busy', 'resource_insufficient', 'resource_device_changed',
      'resource_hidden', 'resource_ambiguous', 'configuration_changed']},
};
function validPair(id: ReadinessCheck, status: ReadinessStatus, code: ReadinessCode) {
  return statusCodes[id][status]?.includes(code) === true;
}

/** Detached, exact public projection; never a browser execution grant. */
export function parseReadinessV2(value: unknown, workflow: ReadinessWorkflow, checkProvider = false): ReadinessV2 {
  const fail = (): never => { throw new Error('Invalid readiness response'); };
  if (!exact(value, ['schema_version', 'workflow', 'checked_at', 'checks', 'policy', 'ready'])
    || value.schema_version !== 2 || value.workflow !== workflow || !['agentic_generation', 'a2_gr00t', 'graph_generation', 'build'].includes(workflow)
    || !(value.checked_at === null || (typeof value.checked_at === 'number' && Number.isFinite(value.checked_at) && value.checked_at > 0))
    || !Array.isArray(value.checks) || value.checks.length !== READINESS_CHECKS.length || typeof value.ready !== 'boolean') return fail();
  const required = new Set<string>(['api_contract', 'runtime']);
  if (workflow === 'agentic_generation' || workflow === 'graph_generation') { required.add('generation_model'); required.add('graph'); }
  if (workflow !== 'graph_generation') required.add('gpu');
  if (workflow === 'a2_gr00t') ['graph', 'policy_protocol', 'policy_model', 'policy_transport'].forEach(id => required.add(id));
  if (checkProvider) required.add('generation_model');
  const seen = new Set();
  for (const row of value.checks) {
    if (!exact(row, ['id', 'status', 'code', 'required']) || typeof row.id !== 'string' || !READINESS_CHECKS.includes(row.id as ReadinessCheck)
      || seen.has(row.id) || row.required !== required.has(row.id)
      || typeof row.status !== 'string' || !['passed', 'not_checked', 'unavailable', 'mismatch', 'blocked', 'not_required'].includes(row.status)
      || typeof row.code !== 'string' || !READINESS_CODES.includes(row.code as ReadinessCode)
      || !validPair(row.id as ReadinessCheck, row.status as ReadinessStatus, row.code as ReadinessCode)
      || (row.required ? row.status === 'not_required' : row.status !== 'not_required')
      || (row.id === 'generation_model' && row.required && !checkProvider
        && (row.status !== 'not_checked' || !['generation_configuration_only', 'generation_not_configured'].includes(row.code)))
      || (value.checked_at === null && row.id !== 'api_contract' && row.status === 'passed')) return fail();
    seen.add(row.id);
  }
  if (value.ready !== value.checks.filter(row => row.required).every(row => row.status === 'passed')
    || (value.policy !== null && workflow !== 'a2_gr00t')) return fail();
  const modelPassed = value.checks.some(row => row.id === 'policy_model' && row.status === 'passed');
  const transportPassed = value.checks.some(row => row.id === 'policy_transport' && row.status === 'passed');
  if (modelPassed !== (value.policy !== null) || (transportPassed && !modelPassed)) return fail();
  if (value.policy !== null) {
    const policy = value.policy;
    if (!exact(policy, ['profile', 'expected_checkpoint', 'instance_id', 'checkpoint_sha256', 'config_sha256', 'serializer_sha256', 'modalities_sha256', 'inference'])
      || policy.profile !== 'gr00t-droid' || policy.expected_checkpoint !== 'nvidia/GR00T-N1.6-DROID' || policy.inference !== 'not_run'
      || typeof policy.instance_id !== 'string' || !/^[a-f0-9]{32}$/.test(policy.instance_id)
      || !['checkpoint_sha256', 'config_sha256', 'serializer_sha256', 'modalities_sha256'].every(key => typeof policy[key] === 'string' && /^[a-f0-9]{64}$/.test(policy[key] as string))
      || !value.checks.some(row => row.id === 'policy_protocol' && row.status === 'passed')) return fail();
  }
  return structuredClone(value) as unknown as ReadinessV2;
}
