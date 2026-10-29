import { StreamHub } from './stream-hub';
const hub = new StreamHub(
  (url) => new EventSource(url, { withCredentials: true }),
  async () => {
    const response = await fetch('/api/session', {
      credentials: 'same-origin',
      cache: 'no-store',
      signal: AbortSignal.timeout(10_000),
    });
    return response.status;
  },
);
const workerScope = self as unknown as { onconnect: (event: MessageEvent) => void };
workerScope.onconnect = (event) => hub.attach(event.ports[0]);
