import type { QueryClient } from '@tanstack/react-query';
import { ApiClient, ApiError } from './api';
import { publishSnapshot } from './cache';
import { isActive } from './contracts';
import { Reconciler } from './reconcile';
import type { ConnectionStatus, HubPort } from './stream-hub';
export interface ObservationPort extends HubPort {
  onmessageerror: ((event: MessageEvent) => void) | null;
  close(): void;
}
export function sharedPort(): ObservationPort | null {
  if (typeof SharedWorker === 'undefined') return null;
  const worker = new SharedWorker(new URL('./events.shared-worker.ts', import.meta.url), {
    type: 'module',
    name: 'arena-workbench-events-v1',
  });
  // A CSP/module load failure may happen after construction; the heartbeat watchdog then degrades.
  return worker.port;
}

/** Snapshot requests never mutate jobs. This coordinator outlives route navigation. */
export class Observation {
  status: ConnectionStatus = 'connecting';
  error = '';
  private state = new Reconciler();
  private port?: ObservationPort;
  private listeners = new Set<() => void>();
  private stopped = false;
  private timer?: ReturnType<typeof setTimeout>;
  private watchdog?: ReturnType<typeof setInterval>;
  private lastPulse = Date.now();
  private budget = 60;
  private refreshing?: Promise<void>;
  constructor(
    private api: ApiClient,
    private cache: QueryClient,
    private makePort = sharedPort,
  ) {}
  subscribe(listener: () => void) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
  private notify() {
    for (const listener of this.listeners) listener();
  }
  async start() {
    try {
      this.port = this.makePort() ?? undefined;
    } catch {
      this.port = undefined;
    }
    if (this.port) {
      // MUST attach before GET: a second tab joins an already-running shared stream.
      this.port.onmessage = ({ data }) => {
        if (this.stopped) return;
        this.lastPulse = Date.now();
        this.port?.postMessage({ type: 'ack' });
        if (data?.type === 'event') {
          this.state.event(data.event);
          this.publish();
          if (this.state.needsResync) void this.refresh();
        } else if (data?.type === 'resync') {
          this.status = 'reconnecting';
          void this.refresh();
        } else if (data?.type === 'status') {
          this.status = data.status;
          if (this.status === 'expired') {
            this.api.expire();
            this.stop();
          } else this.schedule();
        }
        this.notify();
      };
      this.port.onmessageerror = () => this.degrade();
      this.port.start();
      this.watchdog = setInterval(() => {
        if (Date.now() - this.lastPulse > 45_000) this.degrade();
      }, 15_000);
    } else this.status = 'degraded';
    await this.refresh();
  }
  private degrade() {
    this.port?.postMessage({ type: 'leave' });
    this.port?.close();
    this.port = undefined;
    clearInterval(this.watchdog);
    this.status = 'degraded';
    this.schedule();
    this.notify();
  }
  refresh(): Promise<void> {
    if (this.stopped) return Promise.resolve();
    if (this.refreshing) return this.refreshing;
    this.refreshing = (async () => {
      try {
        const raw = await this.cache.fetchQuery({
          queryKey: ['snapshot-wire', 'default'],
          queryFn: () => this.api.get('/workspaces/default'),
          staleTime: 0,
          gcTime: 0,
          retry: false,
        });
        if (this.stopped) return;
        this.state.snapshot(raw);
        this.publish();
        this.error = '';
        this.port?.postMessage({ type: 'ready', cursor: this.state.value!.event_cursor });
      } catch (error) {
        if (this.stopped) return;
        this.error = error instanceof Error ? error.message : 'Workspace unavailable';
        this.status =
          error instanceof ApiError && error.status === 401 ? 'expired' : 'disconnected';
        if (this.status === 'expired') this.stop();
      } finally {
        this.refreshing = undefined;
        this.schedule();
        this.notify();
      }
    })();
    return this.refreshing;
  }
  private publish() {
    if (this.state.value) publishSnapshot(this.cache, this.state.value);
  }
  private schedule() {
    clearTimeout(this.timer);
    if (this.stopped || this.status === 'expired') return;
    const active = !this.state.value || this.state.value.jobs.some(isActive);
    const needed = this.state.needsResync || (this.status !== 'live' && active);
    if (!needed) return;
    if (this.budget <= 0) {
      this.status = 'disconnected';
      this.error =
        'Automatic status checks paused after 60 attempts. Refresh or reconnect to continue.';
      this.notify();
      return;
    }
    this.timer = setTimeout(() => {
      this.budget--;
      void this.refresh();
    }, 5000);
  }
  revoke() {
    this.port?.postMessage({ type: 'revoke' });
    this.stop();
  }
  stop() {
    this.stopped = true;
    clearTimeout(this.timer);
    clearInterval(this.watchdog);
    this.port?.postMessage({ type: 'leave' });
    this.port?.close();
    this.port = undefined;
  }
}
