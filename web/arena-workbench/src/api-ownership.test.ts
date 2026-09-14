import { expect, it, vi } from 'vitest';
import { ApiClient } from './api';
const s1 = { session_id: 's1', csrf_token: 'c1', expires_at: 9999999999 };
const s2 = { ...s1, session_id: 's2', csrf_token: 'c2' };
const reply = (s: unknown, status = 200) => new Response(JSON.stringify(s), { status });
it.each(['activity', 'revoke', 'connect'] as const)('late %s cannot restore or expire a replacement session', async operation => {
  let finish!: (r: Response) => void;
  const api = new ApiClient(vi.fn(() => new Promise<Response>(resolve => { finish = resolve; })));
  api.session = s1;
  const pending = api[operation]().catch(() => undefined);
  api.expire(); api.session = s2;
  finish(reply(operation === 'revoke' ? {} : s1));
  await pending;
  expect(api.session).toBe(s2);
});
it('late 401 cannot expire a same-ID replacement generation', async () => {
  let finish!: (r: Response) => void;
  const api = new ApiClient(vi.fn(() => new Promise<Response>(resolve => { finish = resolve; })));
  api.session = s1;
  const pending = api.get('/jobs').catch(() => undefined);
  api.expire(); api.session = { ...s1 };
  finish(reply({ detail: 'expired' }, 401)); await pending;
  expect(api.session).not.toBeNull();
});
it('valid activity preserves the ownership generation and valid revoke expires it', async () => {
  const api = new ApiClient(vi.fn().mockResolvedValueOnce(reply({ ...s1, expires_at: s1.expires_at + 10 })).mockResolvedValueOnce(reply({})));
  api.session = s1;
  const epoch = api.sessionGeneration;
  await api.activity();
  expect(api.sessionGeneration).toBe(epoch);
  expect(api.session?.expires_at).toBe(s1.expires_at + 10);
  await api.revoke();
  expect(api.session).toBeNull();
  expect(api.sessionGeneration).toBeGreaterThan(epoch);
});
