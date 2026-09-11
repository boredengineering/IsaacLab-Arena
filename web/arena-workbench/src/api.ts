import { isJob, type Job, type JobRequest, type Session } from './contracts';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}
export class ApiClient {
  session: Session | null = null;
  onExpired: () => void = () => {};
  private connecting?: Promise<Session>;
  constructor(private fetcher: typeof fetch = (...args) => fetch(...args)) {}

  connect(): Promise<Session> {
    if (!this.connecting) {
      const establish = () => this.request<Session>('/sessions', 'POST', {});
      const request = globalThis.navigator?.locks
        ? navigator.locks.request('arena-workbench:session', establish)
        : establish();
      this.connecting = request
        .then(async (response) => {
          const s = await response;
          if (
            !s ||
            typeof s.session_id !== 'string' ||
            !s.session_id ||
            typeof s.csrf_token !== 'string' ||
            !s.csrf_token ||
            !Number.isFinite(s.expires_at)
          )
            throw new Error('Invalid session response');
          this.session = s;
          return s;
        })
        .finally(() => {
          this.connecting = undefined;
        });
    }
    return this.connecting;
  }
  get<T>(path: string) {
    return this.request<T>(path, 'GET');
  }
  mutate<T>(path: string, body: unknown, method = 'POST') {
    if (!this.session)
      return Promise.reject(new ApiError('Session unavailable. Reconnect explicitly.', 401));
    return this.request<T>(path, method, body, this.session.csrf_token);
  }
  async activity() {
    this.session = await this.mutate<Session>('/session/activity', {});
    return this.session;
  }
  async revoke() {
    await this.mutate('/session', {}, 'DELETE');
    this.expire();
  }
  expire() {
    this.session = null;
    this.onExpired();
  }

  private async request<T>(
    path: string,
    method: string,
    body?: unknown,
    csrf?: string,
  ): Promise<T> {
    const abort = new AbortController();
    const timeout = setTimeout(() => abort.abort(), 12_000);
    try {
      // Origin is a forbidden browser header: fetch supplies the real origin for these same-origin POSTs.
      const response = await this.fetcher(`/api${path}`, {
        method,
        credentials: 'same-origin',
        cache: 'no-store',
        signal: abort.signal,
        headers: {
          ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
          ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
        },
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      });
      let value: unknown;
      try {
        value = await response.json();
      } catch {
        value = null;
      }
      if (!response.ok) {
        if (response.status === 401) this.expire();
        const detail =
          value && typeof value === 'object' && 'detail' in value
            ? typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail, null, 2)
            : `API unavailable (HTTP ${response.status})`;
        throw new ApiError(detail, response.status);
      }
      if (value === null && response.status !== 204)
        throw new Error('API returned an invalid response');
      return value as T;
    } finally {
      clearTimeout(timeout);
    }
  }
}

const STORAGE_KEY = 'arena:default:pending-diagnostic:v1';
/** Only frozen diagnostic inputs/key are retained; never the session cookie or CSRF token. */
export class PendingJob {
  current: JobRequest | null = null;
  private submitting = false;
  constructor(private storage: Storage) {
    const text = storage.getItem(STORAGE_KEY);
    if (text) {
      try {
        const value = JSON.parse(text) as JobRequest;
        if (
          value.workspace_id !== 'default' ||
          value.kind !== 'diagnostic' ||
          typeof value.idempotency_key !== 'string' ||
          !Number.isInteger(value.inputs?.steps) ||
          value.inputs.steps < 1 ||
          value.inputs.steps > 10 ||
          !Number.isFinite(value.inputs.delay_seconds) ||
          value.inputs.delay_seconds < 0.1 ||
          value.inputs.delay_seconds > 5
        )
          throw new Error();
        this.current = value;
      } catch {
        throw new Error(
          'Unrecognized pending request in browser storage. Resolve it before submitting more jobs.',
        );
      }
    }
  }
  prepare(inputs: JobRequest['inputs']) {
    if (this.current)
      throw new Error('An unresolved request already exists. Retry it before starting another.');
    const request: JobRequest = {
      workspace_id: 'default',
      kind: 'diagnostic',
      idempotency_key: crypto.randomUUID(),
      inputs: { ...inputs },
    };
    this.storage.setItem(STORAGE_KEY, JSON.stringify(request)); // Fail closed if durable tab storage is unavailable.
    this.current = request;
    return request;
  }
  async submit(api: ApiClient) {
    if (!this.current || this.submitting)
      throw new Error('No pending request or submission already in progress');
    this.submitting = true;
    try {
      const result = await api.mutate<Job>('/jobs', this.current);
      if (!isJob(result)) throw new Error('Invalid job response. The request remains unresolved.');
      this.storage.removeItem(STORAGE_KEY);
      this.current = null;
      return result;
    } finally {
      this.submitting = false;
    }
  }
}
