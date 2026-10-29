import { expect, it } from 'vitest';
import * as readiness from './workflow-readiness';
import { READINESS_CHECKS, READINESS_CODES, type ReadinessCheck, type ReadinessV2 } from './readiness-contract';

// Public fixture transcribed from readiness.metadata_v2: configured generation,
// no graph configuration, real contract registered. No provider/runtime executed.
const metadata = () => ({schema_version: 2, workflow: 'graph_generation', checked_at: null,
  checks: [
    {id: 'api_contract', status: 'passed', code: 'api_contract_available', required: true},
    {id: 'runtime', status: 'not_checked', code: 'runtime_not_checked', required: true},
    {id: 'generation_model', status: 'not_checked', code: 'generation_configuration_only', required: true},
    {id: 'graph', status: 'not_checked', code: 'graph_not_configured', required: true},
    {id: 'policy_protocol', status: 'not_required', code: 'not_required', required: false},
    {id: 'policy_model', status: 'not_required', code: 'not_required', required: false},
    {id: 'policy_transport', status: 'not_required', code: 'not_required', required: false},
    {id: 'gpu', status: 'not_required', code: 'not_required', required: false},
  ], policy: null, ready: false});

type Status = ReadinessV2['checks'][number]['status'];
// Source-derived public pairs, not the wider private worker receipt allowlist:
// readiness.metadata_v2/check_v2, readiness_worker.run_checks, probe_provider,
// probe_gpu and policy_readiness.probe_gr00t/validate_probe_result.
const emitted: Record<ReadinessCheck, Partial<Record<Status, readonly string[]>>> = {
  api_contract: {passed: ['api_contract_available'], unavailable: ['api_contract_unavailable']},
  runtime: {not_checked: ['runtime_not_checked'], passed: ['runtime_available'], unavailable: ['runtime_unavailable']},
  generation_model: {
    not_checked: ['generation_configuration_only', 'generation_not_configured'],
    passed: ['generation_model_readable'],
    unavailable: ['generation_not_configured', 'generation_provider_unsupported', 'generation_provider_unavailable',
      'generation_authentication_failed', 'generation_permission_denied', 'generation_model_missing',
      'generation_rate_limited', 'generation_redirect_refused', 'generation_model_mismatch',
      'generation_metadata_invalid', 'generation_check_timeout', 'configuration_changed'],
  },
  graph: {
    not_checked: ['graph_not_configured', 'graph_invalid_configuration', 'graph_not_checked'],
    blocked: ['graph_invalid_configuration'],
    passed: ['graph_retrieval_measured', 'graph_retrieval_structural', 'graph_retrieval_empty'],
    unavailable: ['graph_not_configured', 'graph_retrieval_unavailable', 'configuration_changed'],
  },
  policy_protocol: {not_checked: ['not_checked'], passed: ['policy_protocol_available'],
    unavailable: ['policy_protocol_unavailable'], mismatch: ['policy_modality_mismatch']},
  policy_model: {not_checked: ['not_checked', 'policy_expectation_missing'], passed: ['policy_model_verified'],
    unavailable: ['policy_metadata_unavailable'],
    mismatch: ['policy_modality_mismatch', 'policy_model_mismatch', 'policy_instance_mismatch', 'configuration_changed']},
  policy_transport: {not_checked: ['not_checked', 'policy_transport_unverified'], passed: ['policy_transport_verified']},
  gpu: {not_checked: ['resource_unknown'], passed: ['resource_headroom_observed'],
    blocked: ['resource_unknown', 'resource_lease_busy', 'resource_insufficient', 'resource_device_changed',
      'resource_hidden', 'resource_ambiguous', 'configuration_changed']},
};

function pairResponse(id: ReadinessCheck, status: Status, code: string): ReadinessV2 {
  const value = policyChecked();
  value.ready = false;
  value.policy = null;
  value.checks[2] = {id: 'generation_model', status: 'not_checked', code: 'generation_configuration_only', required: true};
  for (const row of value.checks.filter(row => row.id.startsWith('policy_'))) {
    row.status = 'not_checked'; row.code = 'not_checked';
  }
  if (status === 'passed' && (id === 'policy_model' || id === 'policy_transport')) {
    const verified = policyChecked();
    value.policy = verified.policy;
    value.checks[4] = verified.checks[4];
    value.checks[5] = verified.checks[5];
    value.checks[6].code = 'policy_transport_unverified';
  }
  Object.assign(value.checks.find(row => row.id === id)!, {status, code});
  return value;
}

// Cross every public code with every status for each required check. This catches
// same-prefix and generic-code fallbacks as well as cross-check substitutions.
for (const id of READINESS_CHECKS) {
  it.each<Status>(['passed', 'not_checked', 'unavailable', 'mismatch', 'blocked', 'not_required'])(
    `accepts only backend-emitted ${id}/%s pairs`, status => {
      for (const code of READINESS_CODES) {
        const value = pairResponse(id, status, code);
        const parse = () => readiness.parseReadinessV2(value, 'a2_gr00t', true);
        if (emitted[id][status]?.includes(code)) expect(parse(), `${id}/${status}/${code}`).toEqual(value);
        else expect(parse, `${id}/${status}/${code}`).toThrow('Invalid readiness response');
      }
    });
}

it.each([
  ['runtime', 'mismatch', 'runtime_not_checked'],
  ['gpu', 'unavailable', 'resource_insufficient'],
] as const)('rejects the review counterexample %s/%s/%s', (id, status, code) => {
  expect(() => readiness.parseReadinessV2(pairResponse(id, status, code), 'a2_gr00t', true))
    .toThrow('Invalid readiness response');
});

// Full response projections retain metadata defaults in early returns and worker
// failures. These are fixtures of source branches, not executed dependency probes.
function metadataFor(workflow: ReadinessV2['workflow'], consent: boolean, contract: boolean,
  configured: boolean, graphCode: 'graph_not_configured' | 'graph_invalid_configuration' | 'graph_not_checked'): ReadinessV2 {
  const required = new Set<ReadinessCheck>(['api_contract', 'runtime']);
  if (workflow === 'graph_generation' || workflow === 'agentic_generation') { required.add('generation_model'); required.add('graph'); }
  if (workflow !== 'graph_generation') required.add('gpu');
  if (workflow === 'a2_gr00t') {
    for (const id of ['graph', 'policy_protocol', 'policy_model', 'policy_transport'] as const) required.add(id);
  }
  if (consent) required.add('generation_model');
  const value: ReadinessV2 = {schema_version: 2, workflow, checked_at: null, ready: false, policy: null,
    checks: READINESS_CHECKS.map(id => ({id, required: required.has(id),
      status: required.has(id) ? 'not_checked' : 'not_required', code: required.has(id) ? 'not_checked' : 'not_required'}))};
  for (const row of value.checks) {
    if (row.id === 'api_contract') {
      row.status = contract ? 'passed' : 'unavailable';
      row.code = contract ? 'api_contract_available' : 'api_contract_unavailable';
    } else if (row.id === 'runtime') row.code = 'runtime_not_checked';
    else if (row.required && row.id === 'generation_model') row.code = configured ? 'generation_configuration_only' : 'generation_not_configured';
    else if (row.required && row.id === 'graph') row.code = graphCode;
    else if (row.required && row.id === 'gpu') row.code = 'resource_unknown';
  }
  return value;
}

for (const workflow of ['agentic_generation', 'a2_gr00t', 'graph_generation', 'build'] as const) {
  for (const consent of [false, true]) {
    it(`preserves every metadata configuration for ${workflow}, consent=${consent}`, () => {
      for (const contract of [false, true]) for (const configured of [false, true]) {
        for (const graph of ['graph_not_configured', 'graph_invalid_configuration', 'graph_not_checked'] as const) {
          const value = metadataFor(workflow, consent, contract, configured, graph);
          expect(readiness.parseReadinessV2(value, workflow, consent)).toEqual(value);
          if (workflow !== 'build' && graph === 'graph_invalid_configuration') {
            value.checks[3].status = 'blocked'; // check_v2 returns before timestamp/provider/worker checks.
            expect(readiness.parseReadinessV2(value, workflow, consent)).toEqual(value);
          }
        }
      }
    });
    it(`preserves worker exception/timeout fallback for ${workflow}, consent=${consent}`, () => {
      const value = metadataFor(workflow, consent, true, true, 'graph_not_checked');
      value.checked_at = 123;
      Object.assign(value.checks[1], {status: 'unavailable', code: 'runtime_unavailable'});
      if (consent) Object.assign(value.checks[2], {status: 'unavailable', code: 'generation_provider_unavailable'});
      if (workflow !== 'build') Object.assign(value.checks[3], {status: 'unavailable', code: 'graph_retrieval_unavailable'});
      if (workflow !== 'graph_generation') Object.assign(value.checks[7], {status: 'blocked', code: 'resource_unknown'});
      expect(readiness.parseReadinessV2(value, workflow, consent)).toEqual(value);
    });
  }
  it(`requires provider consent for every observed provider outcome in ${workflow}`, () => {
    for (const status of ['passed', 'unavailable'] as const) for (const code of emitted.generation_model[status]!) {
      const value = metadataFor(workflow, true, true, true, 'graph_not_checked');
      value.checked_at = 123;
      Object.assign(value.checks[2], {status, code});
      expect(readiness.parseReadinessV2(value, workflow, true)).toEqual(value);
      // Keep the required set valid so consent rejection cannot be a shape failure.
      if (workflow !== 'graph_generation' && workflow !== 'agentic_generation') value.checks[2].required = false;
      expect(() => readiness.parseReadinessV2(value, workflow, false)).toThrow('Invalid readiness response');
    }
  });
}

it('retains the complete 47-code inventory without aliases or additions', () => {
  expect(READINESS_CODES).toHaveLength(47);
  expect(new Set(READINESS_CODES).size).toBe(47);
});
it('does not accept legacy required-check sets or policy evidence for the general workflow', () => {
  for (const workflow of ['a2_gr00t', 'graph_generation', 'build'] as const) {
    const value = metadataFor(workflow, false, true, true, 'graph_not_checked');
    expect(() => readiness.parseReadinessV2(value, 'agentic_generation')).toThrow('Invalid readiness response');
    value.workflow = 'agentic_generation'; // Even a relabelled old response is not sufficient.
    expect(() => readiness.parseReadinessV2(value, 'agentic_generation')).toThrow('Invalid readiness response');
  }
  const value = metadataFor('agentic_generation', false, true, true, 'graph_not_checked');
  value.policy = policyChecked().policy;
  expect(() => readiness.parseReadinessV2(value, 'agentic_generation')).toThrow('Invalid readiness response');
});

it('decodes the exact backend v2 metadata without upgrading configuration to readiness', () => {
  expect(readiness.parseReadinessV2(metadata(), 'graph_generation', false)).toEqual(metadata());
});

it.each([
  ['extra field', (r: any) => {r.private = 'synthetic-private-marker';}],
  ['missing check', (r: any) => {r.checks.pop();}],
  ['duplicate check', (r: any) => {r.checks[7] = {...r.checks[0]};}],
  ['unknown code', (r: any) => {r.checks[1].code = 'synthetic-private-marker';}],
  ['extra check field', (r: any) => {r.checks[1].detail = 'synthetic-private-marker';}],
  ['wrong required set', (r: any) => {r.checks[1].required = false;}],
  ['invented pass', (r: any) => {r.checks[1].status = 'passed';}],
  ['cross-check code', (r: any) => {r.checks[1].code = 'policy_model_verified'; r.checks[1].status = 'passed';}],
  ['contradictory ready', (r: any) => {r.ready = true;}],
  ['invalid timestamp', (r: any) => {r.checked_at = -1;}],
  ['wrong policy workflow', (r: any) => {r.policy = {}; }],
])('rejects malformed or contradictory v2 response: %s', (_label, change) => {
  const value = metadata(); change(value);
  expect(() => readiness.parseReadinessV2(value, 'graph_generation', false)).toThrow('Invalid readiness response');
});

// check_v2 + probe_gr00t's public evidence after operator-pinned metadata/codec success.
function policyChecked(): ReadinessV2 {
  return {schema_version: 2, workflow: 'a2_gr00t', checked_at: 123, ready: true,
    checks: [
      {id: 'api_contract', status: 'passed', code: 'api_contract_available', required: true},
      {id: 'runtime', status: 'passed', code: 'runtime_available', required: true},
      {id: 'generation_model', status: 'not_required', code: 'not_required', required: false},
      {id: 'graph', status: 'passed', code: 'graph_retrieval_empty', required: true},
      {id: 'policy_protocol', status: 'passed', code: 'policy_protocol_available', required: true},
      {id: 'policy_model', status: 'passed', code: 'policy_model_verified', required: true},
      {id: 'policy_transport', status: 'passed', code: 'policy_transport_verified', required: true},
      {id: 'gpu', status: 'passed', code: 'resource_headroom_observed', required: true},
    ], policy: {profile: 'gr00t-droid', expected_checkpoint: 'nvidia/GR00T-N1.6-DROID', instance_id: 'a'.repeat(32),
      checkpoint_sha256: 'b'.repeat(64), config_sha256: 'c'.repeat(64), serializer_sha256: 'd'.repeat(64),
      modalities_sha256: 'e'.repeat(64), inference: 'not_run'}};
}
it('preserves exact public policy model and detached evidence without claiming inference', () => {
  const input = policyChecked();
  const result = readiness.parseReadinessV2(input, 'a2_gr00t');
  expect(result).toEqual(input); expect(result.policy).not.toBe(input.policy);
});
it.each([
  ['extra policy field', (r: any) => {r.policy.detail = 'synthetic-private-marker';}],
  ['wrong model', (r: any) => {r.policy.expected_checkpoint = 'nvidia/GR00T-N1.7-DROID';}],
  ['malformed instance', (r: any) => {r.policy.instance_id = 'A'.repeat(32);}],
  ['malformed hash', (r: any) => {r.policy.config_sha256 = 'z'.repeat(64);}],
  ['instance trailing newline', (r: any) => {r.policy.instance_id += '\n';}],
  ['hash trailing newline', (r: any) => {r.policy.config_sha256 += '\n';}],
  ['null identity on pass', (r: any) => {r.policy.instance_id = null;}],
  ['invented inference', (r: any) => {r.policy.inference = 'passed';}],
  ['missing evidence on pass', (r: any) => {r.policy = null;}],
  ['unverified evidence', (r: any) => {r.checks[5].status = 'not_checked'; r.checks[5].code = 'policy_expectation_missing'; r.ready = false;}],
  ['wrong nonpass pair', (r: any) => {r.policy = null; r.checks[5].status = 'unavailable'; r.checks[5].code = 'policy_transport_unverified'; r.checks[6].status = 'not_checked'; r.checks[6].code = 'policy_transport_unverified'; r.ready = false;}],
])('rejects unsupported policy evidence: %s', (_label, change) => {
  const value = policyChecked(); change(value);
  expect(() => readiness.parseReadinessV2(value, 'a2_gr00t')).toThrow('Invalid readiness response');
});
it('rejects provider PASS for a graph-generation request without explicit provider consent', () => {
  const value = metadata(); value.checked_at = 123 as any;
  value.checks[2].status = 'passed'; value.checks[2].code = 'generation_model_readable';
  expect(() => readiness.parseReadinessV2(value, 'graph_generation', false)).toThrow('Invalid readiness response');
  expect(readiness.parseReadinessV2(value, 'graph_generation', true).checks[2].code).toBe('generation_model_readable');
});
