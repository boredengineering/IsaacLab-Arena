import { expect, it } from 'vitest';
import { parseModelSettings, PROVIDERS } from './model-settings-contracts';
const status = { providers: PROVIDERS, configured: true, source: 'session', provider: 'openai',
  model: 'user-model', expires_at: 9999999999, credential_ref: 'public-ref', session_keys_allowed: true };
it('projects only the public contract into the query cache', () => {
  expect(parseModelSettings({ ...status, api_key: 'dummy-secret', masked_key: 'dummy-mask',
    providers: PROVIDERS.map(p => ({ ...p, api_key: 'dummy-secret' })) })).toEqual(status);
});
it.each([
  { providers: [{ id: 'openai', label: 'OpenAI', base_url: 'https://attacker.invalid' }] },
  { providers: null }, { configured: 'yes' }, { source: 'other' }, { credential_ref: null },
  { expires_at: null }, { expires_at: Infinity }, { provider: 'custom' }, { model: null },
  { session_keys_allowed: 'true' }, { model: {} }, { source: 'none' },
])('rejects malformed public metadata without echoing inputs: %j', (bad) => {
  expect(() => parseModelSettings({ ...status, ...bad })).toThrow('Provider settings unavailable');
});
it('accepts server fallback and unconfigured status without a credential reference', () => {
  expect(parseModelSettings({ ...status, source: 'server', expires_at: null, credential_ref: null }).source).toBe('server');
  expect(parseModelSettings({ ...status, source: 'none', configured: false, provider: null, model: null,
    expires_at: null, credential_ref: null }).configured).toBe(false);
});
