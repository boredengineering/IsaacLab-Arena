import { expect, it } from 'vitest';
import { parseModelSettings, parseModelProfile, PROVIDERS } from './model-settings-contracts';
const status = { providers: PROVIDERS, configured: true, source: 'session', provider: 'openai',
  model: 'user-model', expires_at: 9999999999, credential_ref: 'public-ref', session_keys_allowed: true, key_timer_disabled: false };
it('projects only the public contract into the query cache', () => {
  expect(parseModelSettings({ ...status, api_key: 'dummy-secret', masked_key: 'dummy-mask',
    providers: PROVIDERS.map(p => ({ ...p, api_key: 'dummy-secret' })) })).toEqual(status);
});
it.each([
  { providers: [{ id: 'openai', label: 'OpenAI', base_url: 'https://attacker.invalid' }] },
  { providers: null }, { configured: 'yes' }, { source: 'other' }, { credential_ref: null },
  { expires_at: null }, { expires_at: Infinity }, { provider: 'custom' }, { model: null },
  { session_keys_allowed: 'true' }, { model: {} }, { source: 'none' },
  { key_timer_disabled: 'true' }, { key_timer_disabled: null },
])('rejects malformed public metadata without echoing inputs: %j', (bad) => {
  expect(() => parseModelSettings({ ...status, ...bad })).toThrow('Provider settings unavailable');
});
it('accepts server fallback and unconfigured status without a credential reference', () => {
  expect(parseModelSettings({ ...status, source: 'server', expires_at: null, credential_ref: null }).source).toBe('server');
  expect(parseModelSettings({ ...status, source: 'none', configured: false, provider: null, model: null,
    expires_at: null, credential_ref: null }).configured).toBe(false);
});
it('accepts no key timer only with a finite session deadline and defaults older metadata to timed', () => {
  expect(parseModelSettings({ ...status, key_timer_disabled: true }).key_timer_disabled).toBe(true);
  const { key_timer_disabled, ...legacy } = status;
  expect(parseModelSettings(legacy).key_timer_disabled).toBe(false);
  expect(() => parseModelSettings({ ...status, key_timer_disabled: true, expires_at: null })).toThrow();
  expect(() => parseModelSettings({ ...status, key_timer_disabled: true, source: 'server', expires_at: null, credential_ref: null })).toThrow();
});

const profileMetadata = {
  profile_catalogue_version: 'harness-model-profiles/v1',
  profiles: [
    { id: 'openai-gpt-4.1', revision: 1, provider: 'openai', model: 'gpt-4.1',
      endpoint: 'https://api.openai.com/v1', support: 'documented',
      documentation_urls: ['https://platform.openai.com/docs/models/gpt-4.1'],
      request_policy: { api: 'chat_completions', structured_output: 'json_schema',
        temperature_mode: 'configured', token_limit_parameter: 'max_tokens', store: null } },
    { id: 'openai-gpt-6-astra', revision: 1, provider: 'openai', model: 'gpt-6-astra',
      endpoint: 'https://api.openai.com/v1', support: 'documented',
      documentation_urls: ['https://developers.openai.com/api/docs/models/gpt-6-astra'],
      request_policy: { api: 'chat_completions', structured_output: 'json_schema',
        temperature_mode: 'omitted', token_limit_parameter: 'max_completion_tokens', store: false } },
  ],
  effective_profile: { id: null, support: 'unverified', verification: 'not_checked' },
};

const userProfile = { id: 'literal-profile', revision: 1, provider: 'openrouter', model: 'claude-sonnet-latest',
  endpoint: PROVIDERS[2].base_url, origin: 'user_defined', support: 'unverified', verification: 'not_checked', documentation_urls: [],
  request_policy: { api: 'chat_completions', temperature_mode: 'omitted', token_limit_parameter: 'max_completion_tokens',
    structured_output: 'json_object', multimodal_output: 'omitted', store: null } };
it('reserves the custom-entry UI identity rather than accepting an ambiguous catalogue row', () => {
  expect(() => parseModelProfile({ ...userProfile, id: 'custom' })).toThrow();
});
it('decodes exact v2 user profiles without inventing support or losing literal identity', () => {
  const v2 = { ...status, provider: userProfile.provider, model: userProfile.model,
    profile_catalogue_version: 'harness-model-profiles/v2', profile_creation: 'create-only/v1', profiles: [userProfile],
    effective_profile: { id: userProfile.id, support: 'unverified', verification: 'not_checked' } };
  const parsed = parseModelSettings(v2);
  expect(parsed.profiles).toEqual([userProfile]);
  expect(parsed.profile_creation).toBe('create-only/v1');
  expect(parsed.effective_profile).toEqual(v2.effective_profile);
  for (const bad of [
    { ...userProfile, support: 'documented' }, { ...userProfile, revision: true }, { ...userProfile, api_key: 'never-cache' },
    { ...userProfile, id: 'openai-gpt-4.1' }, { ...userProfile, endpoint: 'https://elsewhere.invalid' },
    { ...userProfile, request_policy: { ...userProfile.request_policy, store: true } },
    { ...userProfile, request_policy: { ...userProfile.request_policy, temperature: 0.2 } },
    { ...userProfile, request_policy: { ...userProfile.request_policy, multimodal_output: undefined } },
  ]) {
    const rejected = parseModelSettings({ ...v2, profiles: [bad] });
    expect(rejected.profile_metadata_invalid).toBe(true);
    expect(rejected.profile_creation).toBeUndefined();
    expect(rejected.configured).toBe(true);
    expect(rejected.profiles).toBeUndefined();
  }
  expect(parseModelSettings({ ...v2, profiles: [userProfile, userProfile] }).profile_metadata_invalid).toBe(true);
  expect(parseModelSettings({ ...status, ...profileMetadata, profile_creation: 'create-only/v1' }).profile_creation).toBeUndefined();
});

it('projects documented profile metadata without retaining unexpected nested fields', () => {
  const input = structuredClone(profileMetadata);
  Object.assign(input.profiles[0], { api_key: 'dummy-profile-secret' });
  Object.assign(input.profiles[0].request_policy, { private: 'dummy-profile-secret' });
  Object.assign(input.effective_profile, { raw: 'dummy-profile-secret' });
  const parsed = parseModelSettings({ ...status, ...input });
  expect(parsed).toMatchObject(profileMetadata);
  expect(JSON.stringify(parsed)).not.toContain('dummy-profile-secret');
  expect(parsed.profiles).not.toBe(input.profiles);
});

it.each(profileMetadata.profiles)('binds documented support to exact $id identity, never to a similar model name', profile => {
  const metadata = { ...profileMetadata, effective_profile: { id: profile.id, support: 'documented', verification: 'not_checked' } };
  expect(parseModelSettings({ ...status, ...metadata, model: profile.model }).effective_profile).toEqual(metadata.effective_profile);
  for (const model of [profile.model + '-custom', profile.model.toUpperCase()]) {
    expect(parseModelSettings({ ...status, ...metadata, model }).profile_metadata_invalid).toBe(true);
  }
  expect(parseModelSettings({ ...status, ...metadata, source: 'server', provider: 'unknown-provider',
    model: profile.model, credential_ref: null, expires_at: null }).profile_metadata_invalid).toBe(true);
});

it('keeps older metadata and unknown-provider server fallback configured but unverified', () => {
  expect(parseModelSettings(status).profiles).toBeUndefined();
  const unknown = { ...status, source: 'server', provider: 'unknown-provider', credential_ref: null, expires_at: null };
  expect(parseModelSettings(unknown)).toMatchObject({ configured: true, provider: 'unknown-provider' });
  expect(parseModelSettings({ ...unknown, ...profileMetadata }).effective_profile).toEqual(profileMetadata.effective_profile);
  expect(parseModelSettings({ ...status, ...profileMetadata, configured: false, source: 'none', provider: null,
    model: null, credential_ref: null, expires_at: null, effective_profile: null }).effective_profile).toBeNull();
});

it.each([
  { profile_catalogue_version: 'future/v2' }, { profiles: null }, { profiles: [null] },
  { profiles: [{ ...profileMetadata.profiles[0], id: 'future-profile' }] },
  { profiles: [{ ...profileMetadata.profiles[0], id: ['openai-gpt-4.1'] }] },
  { profiles: [profileMetadata.profiles[0], profileMetadata.profiles[0]] },
  { profiles: [{ ...profileMetadata.profiles[0], revision: 2 }] },
  { profiles: [{ ...profileMetadata.profiles[0], support: 'tested' }] },
  { profiles: [{ ...profileMetadata.profiles[0], endpoint: 'https://dummy-private.invalid' }] },
  { profiles: [{ ...profileMetadata.profiles[0], documentation_urls: ['javascript:dummy-private'] }] },
  { profiles: [{ ...profileMetadata.profiles[0], documentation_urls: ['https://platform.openai.com@dummy-private.invalid/'] }] },
  { profiles: [{ ...profileMetadata.profiles[0], request_policy: { api: 'responses' } }] },
  { effective_profile: { id: null, support: 'unverified', verification: 'passed' } },
  { effective_profile: { id: 'unknown', support: 'documented', verification: 'not_checked' } },
  { effective_profile: null }, { effective_profile: undefined },
])('refuses malformed additive metadata without losing credential status or caching raw values: %j', bad => {
  const parsed = parseModelSettings({ ...status, ...profileMetadata, ...bad });
  expect(parsed).toMatchObject({ configured: true, profile_metadata_invalid: true });
  expect(parsed.profiles).toBeUndefined();
  expect(parsed.effective_profile).toBeUndefined();
  expect(JSON.stringify(parsed)).not.toContain('dummy-private');
});

it('refuses policies that contradict the frozen profile revision rather than relabelling them documented', () => {
  const profiles = structuredClone(profileMetadata.profiles);
  profiles[1].request_policy.temperature_mode = 'configured';
  expect(parseModelSettings({ ...status, ...profileMetadata, profiles }).profile_metadata_invalid).toBe(true);
});
