import { beforeEach, expect, it, vi } from 'vitest';
import { ApiClient, PendingJob } from './api';
const session = { session_id: 's1', csrf_token: 'csrf', expires_at: 9000 };
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
beforeEach(() => sessionStorage.clear());
it('preserves structured editor diagnostics in error messages', async () => {
  const api = new ApiClient(vi.fn().mockResolvedValue(reply({ detail: { message: 'Invalid Arena environment specification', errors: ['Unknown asset'] } }, 422)));
  await expect(api.get('/editor')).rejects.toThrow('Unknown asset');
});
it('establishes a cookie session, adds CSRF only to mutations, and does not renew on reads', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(reply(session))
    .mockResolvedValueOnce(reply({ jobs: [] }))
    .mockResolvedValueOnce(reply({ resumed: true }));
  const api = new ApiClient(fetcher);
  await api.connect();
  await api.get('/jobs');
  await api.mutate('/jobs/resume-queue', {});
  expect(fetcher.mock.calls[0][0]).toBe('/api/sessions');
  expect(fetcher.mock.calls[0][1]).toMatchObject({
    method: 'POST',
    credentials: 'same-origin',
    body: '{}',
  });
  expect(new Headers(fetcher.mock.calls[2][1].headers).get('X-CSRF-Token')).toBe('csrf');
  expect(fetcher.mock.calls.map((c) => c[0])).not.toContain('/api/session/activity');
  expect(new Headers(fetcher.mock.calls[0][1].headers).has('Origin')).toBe(false); // Browser owns forbidden Origin header.
});
it('keeps the exact ambiguous request across reload and replacement session until an explicit retry succeeds', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(reply(session))
    .mockRejectedValueOnce(new TypeError('network lost'));
  const api = new ApiClient(fetcher);
  await api.connect();
  const pending = new PendingJob(sessionStorage);
  const request = pending.prepare({ steps: 3, delay_seconds: 1 });
  await expect(pending.submit(api)).rejects.toThrow('network lost');
  const reloaded = new PendingJob(sessionStorage);
  expect(reloaded.current).toEqual(request);
  expect(() => reloaded.prepare({ steps: 9, delay_seconds: 2 })).toThrow(/unresolved/i);
  expect(fetcher).toHaveBeenCalledTimes(2); // No constructor/reload mutation.
  fetcher
    .mockResolvedValueOnce(reply({ ...session, csrf_token: 'new' }))
    .mockResolvedValueOnce(
      reply(
        {
          id: 'j1',
          workspace_id: 'default',
          kind: 'diagnostic',
          status: 'queued',
          stage: 'queued',
          inputs: { steps: 3, delay_seconds: 1 },
        },
        202,
      ),
    );
  await api.connect();
  await reloaded.submit(api);
  expect(JSON.parse(fetcher.mock.calls[3][1].body)).toEqual(request);
  expect(new Headers(fetcher.mock.calls[3][1].headers).get('X-CSRF-Token')).toBe('new');
  expect(reloaded.current).toBeNull();
});
it('revokes locally on 401 without automatically creating a replacement session', async () => {
  const expired = vi.fn();
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(reply(session))
    .mockResolvedValueOnce(reply({ detail: 'expired' }, 401));
  const api = new ApiClient(fetcher);
  api.onExpired = expired;
  await api.connect();
  await expect(api.get('/jobs')).rejects.toThrow('expired');
  expect(api.session).toBeNull();
  expect(expired).toHaveBeenCalledOnce();
  expect(fetcher).toHaveBeenCalledTimes(2);
});
it('retains a request if a successful HTTP response does not contain an authoritative job', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(reply(session))
    .mockResolvedValueOnce(reply({ accepted: true }, 202));
  const api = new ApiClient(fetcher);
  await api.connect();
  const pending = new PendingJob(sessionStorage);
  const request = pending.prepare({ steps: 2, delay_seconds: 1 });
  await expect(pending.submit(api)).rejects.toThrow(/invalid job/i);
  expect(new PendingJob(sessionStorage).current).toEqual(request);
});
it('rejects malformed sessions rather than enabling unprotected mutations', async () => {
  const api = new ApiClient(vi.fn().mockResolvedValue(reply({ session_id: 's' })));
  await expect(api.connect()).rejects.toThrow(/invalid session/i);
  expect(api.session).toBeNull();
});
it('serializes browser session creation with an origin-scoped Web Lock where supported', async () => {
  const request = vi.fn(async (_name, callback) => callback());
  Object.defineProperty(navigator, 'locks', { value: { request }, configurable: true });
  try {
    const api = new ApiClient(vi.fn().mockResolvedValue(reply(session)));
    await api.connect();
    expect(request).toHaveBeenCalledWith('arena-workbench:session', expect.any(Function));
  } finally {
    Object.defineProperty(navigator, 'locks', { value: undefined, configurable: true });
  }
});
