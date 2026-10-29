import { afterEach, expect, it, vi } from 'vitest';
import { StreamHub } from './stream-hub';
class Source extends EventTarget {
  close = vi.fn();
  send(type: string, data?: unknown) {
    this.dispatchEvent(new MessageEvent(type, { data: JSON.stringify(data) }));
  }
}
class Port {
  onmessage: ((event: MessageEvent) => void) | null = null;
  postMessage = vi.fn();
  start() {}
  close() {}
  send(data: unknown) {
    this.onmessage?.(new MessageEvent('message', { data }));
  }
}
afterEach(() => vi.useRealTimers());
it('multiplexes one EventSource across MessagePorts and closes only after the final subscriber leaves', () => {
  const source = new Source();
  const create = vi.fn(() => source as unknown as EventSource);
  const hub = new StreamHub(create, async () => 200);
  const a = new Port(),
    b = new Port();
  hub.attach(a);
  hub.attach(b);
  a.send({ type: 'ready', cursor: 2 });
  b.send({ type: 'ready', cursor: 4 });
  expect(create).toHaveBeenCalledTimes(1);
  expect(create).toHaveBeenCalledWith('/api/events?after=2');
  source.send('open');
  const job = {
    id: 'j',
    workspace_id: 'default',
    kind: 'diagnostic',
    status: 'running',
    stage: 'step',
    inputs: { steps: 2, delay_seconds: 1 },
  };
  source.send('job', {
    schema_version: 1,
    id: 3,
    workspace_id: 'default',
    job_id: 'j',
    kind: 'stage',
    job,
  });
  expect(a.postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'event' }));
  expect(b.postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'event' }));
  a.send({ type: 'leave' });
  expect(source.close).not.toHaveBeenCalled();
  b.send({ type: 'leave' });
  expect(source.close).toHaveBeenCalledOnce();
  hub.dispose();
});
it('closes for a journal gap and resumes only from a new snapshot cursor', () => {
  const sources: Source[] = [];
  const create = vi.fn(() => {
    const s = new Source();
    sources.push(s);
    return s as unknown as EventSource;
  });
  const hub = new StreamHub(create, async () => 200);
  const port = new Port();
  hub.attach(port);
  port.send({ type: 'ready', cursor: 8 });
  sources[0].send('resync_required');
  expect(sources[0].close).toHaveBeenCalled();
  expect(port.postMessage).toHaveBeenCalledWith({ type: 'resync' });
  port.send({ type: 'ready', cursor: 30 });
  expect(create).toHaveBeenLastCalledWith('/api/events?after=30');
  hub.dispose();
});
it('detects session revocation on stream failure without reconnecting or issuing a session POST', async () => {
  vi.useFakeTimers();
  const source = new Source();
  const create = vi.fn(() => source as unknown as EventSource);
  const probe = vi.fn(async () => 401);
  const hub = new StreamHub(create, probe);
  const port = new Port();
  hub.attach(port);
  port.send({ type: 'ready', cursor: 0 });
  source.send('error');
  await vi.advanceTimersByTimeAsync(60_000);
  expect(port.postMessage).toHaveBeenCalledWith({ type: 'status', status: 'expired' });
  expect(create).toHaveBeenCalledOnce();
  expect(probe).toHaveBeenCalled();
  hub.dispose();
});
it('backs off reconnects while explicitly degrading and bounds unacknowledged subscriber events', async () => {
  vi.useFakeTimers();
  const sources: Source[] = [];
  const create = vi.fn(() => {
    const s = new Source();
    sources.push(s);
    return s as unknown as EventSource;
  });
  const hub = new StreamHub(create, async () => 200);
  const port = new Port();
  hub.attach(port);
  port.send({ type: 'ready', cursor: 0 });
  for (let i = 0; i < 3; i++) {
    sources[i].send('error');
    await vi.advanceTimersByTimeAsync(1000 * 2 ** i);
  }
  expect(port.postMessage).toHaveBeenCalledWith({ type: 'status', status: 'degraded' });
  const job = {
    id: 'j',
    workspace_id: 'default',
    kind: 'diagnostic',
    status: 'running',
    stage: 'step',
    inputs: { steps: 2, delay_seconds: 1 },
  };
  for (let id = 1; id <= 500; id++)
    sources[3].send('job', {
      schema_version: 1,
      id,
      workspace_id: 'default',
      job_id: 'j',
      kind: 'stage',
      job,
    });
  expect(
    port.postMessage.mock.calls.filter(([m]) => m.type === 'event').length,
  ).toBeLessThanOrEqual(128);
  expect(port.postMessage).toHaveBeenCalledWith({ type: 'resync' });
  hub.dispose();
});
it('also bounds heartbeat messages queued for a suspended subscriber', async () => {
  vi.useFakeTimers();
  const source = new Source();
  const port = new Port();
  const hub = new StreamHub(
    () => source as unknown as EventSource,
    async () => 200,
  );
  hub.attach(port);
  port.send({ type: 'ready', cursor: 0 });
  await vi.advanceTimersByTimeAsync(15_000 * 300);
  expect(port.postMessage.mock.calls.length).toBeLessThanOrEqual(130);
  expect(port.postMessage).toHaveBeenCalledWith({ type: 'resync' });
  hub.dispose();
});
it('allows a newly established session to attach after revocation without inheriting the expired status', () => {
  const source = new Source();
  const create = vi.fn(() => source as unknown as EventSource);
  const hub = new StreamHub(create, async () => 200);
  const old = new Port();
  hub.attach(old);
  old.send({ type: 'ready', cursor: 0 });
  old.send({ type: 'revoke' });
  old.send({ type: 'leave' });
  const fresh = new Port();
  hub.attach(fresh);
  fresh.send({ type: 'ready', cursor: 2 });
  expect(fresh.postMessage).not.toHaveBeenCalledWith({ type: 'status', status: 'expired' });
  expect(create).toHaveBeenCalledTimes(2);
  hub.dispose();
});
