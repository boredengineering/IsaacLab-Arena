import { describe, expect, it, vi } from 'vitest';
import { ControlClient, ControlError, decodeOperation, decodeServiceStatus } from './control-api';
const revision = 'a'.repeat(64), id = 'b'.repeat(32), csrf = 'c'.repeat(64);
const operation = {request_id: id, profile_revision: revision, status: 'completed', code: 'services_started'};
const metadata = () => ({schema_version: 1, profile_revision: revision, expected_policy: 'nvidia/GR00T-N1.6-DROID', services: ['arena', 'neo4j', 'gr00t'].map(id => ({id, status: 'running'})), api: 'healthy', startup_allowed: true, operation: null});
const response = (v: unknown, status = 200) => new Response(JSON.stringify(v), {status});
const paired = (csrf_token = csrf) => ({schema_version: 1, csrf_token, expires_at: 9999999999});

describe('exact control wire', () => {
  it('refuses active CSRF reflected into a public profile before it can reach retention or UI', async () => {
    const transport = vi.fn(async (url: RequestInfo | URL) => response(String(url) === '/control/session' ? paired() : {...metadata(), profile_revision: csrf}));
    const client = new ControlClient(transport);
    await client.pair('synthetic-pairing-token');
    await expect(client.observe()).rejects.toThrow(ControlError);
  });
  it.each([
    {extra: 'synthetic-secret'}, {schema_version: 2}, {profile_revision: revision.toUpperCase()}, {expected_policy: 'unapproved'}, {api: 'ready'}, {startup_allowed: 1},
    {services: [{id:'arena',status:'running'}]}, {services: ['neo4j','arena','gr00t'].map(id => ({id,status:'running'}))}, {services: ['arena','neo4j','gr00t'].map(id => ({id,status:'ready'}))},
    {operation: {...operation, status:'starting'}}, {operation: {...operation, request_id: id.toUpperCase()}}, {operation: {...operation, extra: true}},
  ])('rejects malformed service projection %j', change => expect(() => decodeServiceStatus({...metadata(), ...change})).toThrow(ControlError));
  it('decodes the actual ordered service and status-code contracts into detached values', () => {
    const source = {...metadata(), operation};
    const next = decodeServiceStatus(source);
    expect(next).toEqual(source); expect(next).not.toBe(source); expect(next.services[0]).not.toBe(source.services[0]);
    for (const [status,code] of [['starting','starting'],['completed','services_started'],['unknown','start_unknown'],['failed','start_failed'],['failed','profile_mismatch'],['failed','resource_unavailable'],['failed','api_unavailable']]) expect(decodeOperation({...operation,status,code})).toEqual({...operation,status,code});
  });
  it('uses fixed routes, cookie credentials and memory-only CSRF; Start and GET both require exact targets', async () => {
    const wire = vi.fn(async (url: RequestInfo | URL) => response(String(url) === '/control/session' ? paired() : String(url).endsWith('/start') ? operation : {...metadata(),operation}, String(url).endsWith('/start') ? 202 : 200));
    const client = new ControlClient(wire);
    await client.pair('synthetic-pairing-token');
    await client.start({request_id:id, profile_revision:revision}); await client.observe({request_id:id, profile_revision:revision});
    expect(wire.mock.calls.map(c => c[0])).toEqual(['/control/session','/control/research-services/start',`/control/research-services?request_id=${id}`]);
    const calls = wire.mock.calls as unknown as [string,RequestInit][];
    expect(calls[1][1]).toMatchObject({method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error',headers:{'X-CSRF-Token':csrf},body:JSON.stringify({request_id:id,profile_revision:revision})});
    expect(JSON.stringify(client)).not.toMatch(/synthetic-pairing-token|c{64}/);
    await expect(client.observe({request_id:'e'.repeat(32), profile_revision:revision})).rejects.toThrow(ControlError);
    await expect(client.start({request_id:id, profile_revision:'e'.repeat(64)})).rejects.toThrow(ControlError);
  });
  it.each([401,403,404,409,429,503])('never exposes raw HTTP %i diagnostics or retries', async status => {
    const wire = vi.fn(async () => response({error:'synthetic-private-secret'},status));
    const client = new ControlClient(wire);
    await expect(client.pair('synthetic-pairing-token')).rejects.not.toThrow('synthetic-private-secret');
    expect(wire).toHaveBeenCalledTimes(1); expect(client.paired).toBe(false);
  });
  it('bounds streamed response bytes before JSON projection', async () => {
    const client = new ControlClient(vi.fn(async () => new Response(' '.repeat(8193)+JSON.stringify(paired()))));
    await expect(client.pair()).rejects.toThrow(ControlError);
  });
  it('drops late replaced-owner pairing without reviving old credentials', async () => {
    let finish!: (v:Response)=>void;
    const wire = vi.fn().mockImplementationOnce(() => new Promise<Response>(resolve => {finish=resolve;})).mockResolvedValue(response(paired()));
    const client = new ControlClient(wire);
    const first = client.pair('old'); const checked = expect(first).rejects.toThrow(ControlError);
    await client.pair('new'); const generation = client.generation;
    finish(response(paired('d'.repeat(64)))); await checked;
    expect(client.generation).toBe(generation); expect(client.paired).toBe(true);
  });
  it('rejects duplicate JSON authority fields even when the last value is valid', async () => {
    const client = new ControlClient(vi.fn(async () => new Response(`{"schema_version":0,"schema_version":1,"csrf_token":"${csrf}","expires_at":9999999999}`)));
    await expect(client.pair('synthetic-pairing-token')).rejects.toThrow(ControlError);
    expect(client.paired).toBe(false);
  });
  it('aborts the response transport even when an error body is deliberately not consumed', async () => {
    let signal: AbortSignal | null | undefined;
    const client = new ControlClient(vi.fn(async (_url, init) => {signal=init?.signal; return response({error:'synthetic-private'},503);}));
    await expect(client.pair()).rejects.toThrow(ControlError);
    expect(signal?.aborted).toBe(true);
  });
  it('rejects success-shaped responses under a non-contract HTTP status', async () => {
    const client = new ControlClient(vi.fn(async () => response(paired(), 201)));
    await expect(client.pair()).rejects.toThrow(ControlError);
  });
  it('labels missing pairing route as unavailable, not a nonexistent startup request', async () => {
    const client = new ControlClient(vi.fn(async () => response({error:'not_found'},404)));
    await expect(client.pair()).rejects.toThrow('Control helper unavailable or not configured.');
  });
  it('rejects non-wire CSRF tokens rather than storing them as control authority', async () => {
    const client = new ControlClient(vi.fn(async () => response(paired('synthetic-invalid-secret'))));
    await expect(client.pair('synthetic-pairing-token')).rejects.toThrow(ControlError);
    expect(client.paired).toBe(false);
  });
});
