import { isEvent } from './contracts';
export type ConnectionStatus =
  | 'connecting'
  | 'live'
  | 'reconnecting'
  | 'degraded'
  | 'expired'
  | 'disconnected';
export interface HubPort {
  onmessage: ((event: MessageEvent) => void) | null;
  postMessage(message: unknown): void;
  start(): void;
}
interface Subscriber {
  unacked: number;
  paused: boolean;
}
/** One instance lives in the named SharedWorker, not in a tab or route. */
export class StreamHub {
  private ports = new Map<HubPort, Subscriber>();
  private source?: EventSource;
  private cursor = 0;
  private failures = 0;
  private status: ConnectionStatus = 'connecting';
  private retry?: ReturnType<typeof setTimeout>;
  private stable?: ReturnType<typeof setTimeout>;
  private pulse?: ReturnType<typeof setInterval>;
  private probing = false;
  private generation = 0;
  constructor(
    private create: (url: string) => EventSource,
    private sessionStatus: () => Promise<number>,
  ) {}

  attach(port: HubPort) {
    // Tabs attach only after an explicit successful session establishment.
    if (this.status === 'expired') {
      this.status = 'connecting';
      this.failures = 0;
    }
    this.ports.set(port, { unacked: 0, paused: false });
    port.onmessage = ({ data }) => {
      if (data?.type === 'leave') {
        this.ports.delete(port);
        if (!this.ports.size) this.dispose();
      } else if (data?.type === 'ack') {
        const subscriber = this.ports.get(port);
        if (subscriber) subscriber.unacked = Math.max(0, subscriber.unacked - 1);
      } else if (data?.type === 'revoke') {
        this.expire();
      } else if (data?.type === 'ready' && Number.isSafeInteger(data.cursor) && data.cursor >= 0) {
        this.ports.set(port, { unacked: 0, paused: false });
        if (!this.source && !this.retry) {
          this.cursor = data.cursor;
          this.open();
        }
      }
    };
    port.start();
    port.postMessage({ type: 'status', status: this.status });
    if (!this.pulse)
      this.pulse = setInterval(() => {
        this.broadcast({ type: 'pulse' });
        if (this.status !== 'expired') void this.probe();
      }, 15_000);
  }
  private send(port: HubPort, message: unknown) {
    const subscriber = this.ports.get(port);
    if (!subscriber || subscriber.paused) return;
    if (subscriber.unacked >= 128) {
      subscriber.paused = true;
      port.postMessage({ type: 'resync' });
    } else {
      subscriber.unacked++;
      port.postMessage(message);
    }
  }
  private broadcast(message: unknown, force = false) {
    for (const port of this.ports.keys()) {
      try {
        if (force) port.postMessage(message);
        else this.send(port, message);
      } catch {
        this.ports.delete(port);
      }
    }
  }
  private setStatus(status: ConnectionStatus) {
    this.status = status;
    this.broadcast({ type: 'status', status }, status === 'expired');
  }
  private open() {
    if (!this.ports.size || this.source) return;
    this.setStatus(this.failures >= 3 ? 'degraded' : this.failures ? 'reconnecting' : 'connecting');
    const source = this.create(`/api/events?after=${this.cursor}`);
    this.source = source;
    source.addEventListener('open', () => {
      if (this.source !== source) return;
      this.setStatus('live');
      this.stable = setTimeout(() => {
        this.failures = 0;
      }, 15_000);
    });
    source.addEventListener('job', (raw) => {
      if (this.source !== source) return;
      let event: unknown;
      try {
        event = JSON.parse((raw as MessageEvent).data);
      } catch {
        this.resync();
        return;
      }
      if (!isEvent(event)) {
        this.resync();
        return;
      }
      if (event.id <= this.cursor) return;
      if (event.id !== this.cursor + 1) {
        this.resync();
        return;
      }
      this.cursor = event.id;
      this.broadcast({ type: 'event', event });
    });
    source.addEventListener('resync_required', () => {
      if (this.source === source) this.resync();
    });
    for (const name of ['session_expired', 'session_revoked'])
      source.addEventListener(name, () => {
        if (this.source === source) this.expire();
      });
    source.addEventListener('error', () => {
      if (this.source !== source) return;
      this.closeSource();
      this.failures++;
      this.setStatus(this.failures >= 3 ? 'degraded' : 'reconnecting');
      void this.probe();
      this.retry = setTimeout(
        () => {
          this.retry = undefined;
          this.open();
        },
        Math.min(30_000, 1000 * 2 ** (this.failures - 1)),
      );
    });
  }
  private async probe() {
    if (this.probing || !this.ports.size) return;
    this.probing = true;
    const generation = this.generation;
    try {
      const status = await this.sessionStatus();
      if (generation === this.generation && status === 401) this.expire();
    } catch {
      /* Stream backoff and tab status polling handle unavailable API. */
    } finally {
      this.probing = false;
    }
  }
  private resync() {
    this.closeSource();
    this.broadcast({ type: 'resync' });
  }
  private expire() {
    this.generation++;
    this.closeSource();
    clearTimeout(this.retry);
    this.retry = undefined;
    this.setStatus('expired');
  }
  private closeSource() {
    this.source?.close();
    this.source = undefined;
    clearTimeout(this.stable);
  }
  dispose() {
    this.generation++;
    this.closeSource();
    clearTimeout(this.retry);
    clearInterval(this.pulse);
    this.retry = undefined;
    this.pulse = undefined;
    this.ports.clear();
  }
}
