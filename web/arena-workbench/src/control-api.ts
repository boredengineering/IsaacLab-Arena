// Fixed same-origin control protocol; no Arena client, query cache or storage authority.
export const EXPECTED_POLICY = 'nvidia/GR00T-N1.6-DROID';
const HEX32 = /^[0-9a-f]{32}$/;
const HEX64 = /^[0-9a-f]{64}$/;
export type StartRequest = { request_id: string; profile_revision: string };
export type ControlOperation = StartRequest & { status: 'starting' | 'completed' | 'failed' | 'unknown'; code: string };
export interface ServiceStatus {
  schema_version: 1;
  profile_revision: string;
  expected_policy: typeof EXPECTED_POLICY;
  services: { id: 'arena' | 'neo4j' | 'gr00t'; status: 'running' | 'stopped' | 'missing' | 'mismatch' | 'unknown' }[];
  api: 'healthy' | 'stopped' | 'unavailable' | 'unknown';
  startup_allowed: boolean;
  operation: ControlOperation | null;
}
export class ControlError extends Error {
  constructor(public readonly code: 'unavailable' | 'invalid' | 'unauthorized' | 'not_found' | 'retired' = 'unavailable') {
    super({ unavailable: 'Control helper unavailable or not configured.', invalid: 'Control response could not be verified.', unauthorized: 'Control pairing expired or was rejected. Pair or recover explicitly.', not_found: 'Exact request not found. Acceptance remains unresolved; do not start a replacement.', retired: 'Control ownership changed. Review the current control session.' }[code]);
  }
}
function exact(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length !== keys.length || keys.some(k => !Object.hasOwn(value, k))) throw new ControlError('invalid');
  return value as Record<string, unknown>;
}
function literal<T extends string>(value: unknown, values: readonly T[]): T {
  if (typeof value !== 'string' || !values.includes(value as T)) throw new ControlError('invalid');
  return value as T;
}
function hex(value: unknown, pattern: RegExp): string {
  if (typeof value !== 'string' || !pattern.test(value)) throw new ControlError('invalid');
  return value;
}
export function decodeOperation(value: unknown): ControlOperation {
  const v = exact(value, ['request_id', 'profile_revision', 'status', 'code']);
  const status = literal(v.status, ['starting', 'completed', 'failed', 'unknown'] as const);
  const codes = { starting: ['starting'], completed: ['services_started'], failed: ['start_failed', 'profile_mismatch', 'resource_unavailable', 'api_unavailable'], unknown: ['start_unknown'] };
  return { request_id: hex(v.request_id, HEX32), profile_revision: hex(v.profile_revision, HEX64), status, code: literal(v.code, codes[status]) };
}
export function decodeServiceStatus(value: unknown): ServiceStatus {
  const v = exact(value, ['schema_version', 'profile_revision', 'expected_policy', 'services', 'api', 'startup_allowed', 'operation']);
  if (v.schema_version !== 1 || v.expected_policy !== EXPECTED_POLICY || typeof v.startup_allowed !== 'boolean' || !Array.isArray(v.services) || v.services.length !== 3) throw new ControlError('invalid');
  const ids = ['arena', 'neo4j', 'gr00t'] as const;
  return { schema_version: 1, profile_revision: hex(v.profile_revision, HEX64), expected_policy: EXPECTED_POLICY,
    services: v.services.map((s, i) => { const row = exact(s, ['id', 'status']); return { id: literal(row.id, [ids[i]]), status: literal(row.status, ['running', 'stopped', 'missing', 'mismatch', 'unknown'] as const) }; }),
    api: literal(v.api, ['healthy', 'stopped', 'unavailable', 'unknown'] as const), startup_allowed: v.startup_allowed,
    operation: v.operation === null ? null : decodeOperation(v.operation) };
}
// JSON.parse validates syntax; the lexical walk also refuses escaped duplicate keys.
function uniqueJson(text: string): unknown {
  let value: unknown;
  try { value = JSON.parse(text); } catch { throw new ControlError('invalid'); }
  const tokens = text.match(/"(?:[^"\\]|\\.)*"|[{}\[\]:,]|[^\s{}\[\]:,]+/g) ?? [];
  const stack: (Set<string> | null)[] = [];
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (token === '{' || token === '[') { stack.push(token === '{' ? new Set() : null); if (stack.length > 16) throw new ControlError('invalid'); }
    else if (token === '}' || token === ']') stack.pop();
    else if (token.startsWith('"') && tokens[i + 1] === ':') {
      const keys = stack[stack.length - 1]; const key = JSON.parse(token) as string;
      if (!keys || keys.has(key)) throw new ControlError('invalid');
      keys.add(key);
    }
  }
  return value;
}
export class ControlClient {
  #csrf: string | null = null;
  #expires = 0;
  #generation = 0;
  constructor(private readonly transport: typeof fetch = (...args) => fetch(...args)) {}
  get generation() { return this.#generation; }
  get paired() { return !!this.#csrf && this.#expires > Date.now() / 1000; }
  retire() { this.#generation++; this.#csrf = null; this.#expires = 0; }
  private async request(path: string, method: 'GET' | 'POST' | 'DELETE', body?: unknown): Promise<unknown> {
    const owner = this.#generation;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await this.transport(path, { method, credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', ...(method !== 'GET' && this.#csrf ? { 'X-CSRF-Token': this.#csrf } : {}) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      if (owner !== this.#generation) throw new ControlError('retired');
      if (!response.ok) {
        if (response.status === 401 || response.status === 403) { this.retire(); throw new ControlError('unauthorized'); }
        throw new ControlError(response.status === 404 && path.includes('?request_id=') ? 'not_found' : 'unavailable');
      }
      if (response.status !== (path.endsWith('/start') ? 202 : 200)) throw new ControlError('invalid');
      const reader = response.body?.getReader();
      if (!reader) throw new ControlError('invalid');
      let size = 0;
      const chunks: Uint8Array[] = [];
      try { for (;;) { const { done, value } = await reader.read(); if (done) break; size += value.byteLength; if (size > 8192) throw new ControlError('invalid'); chunks.push(value); } }
      finally { await reader.cancel(); }
      if (owner !== this.#generation) throw new ControlError('retired');
      const bytes = new Uint8Array(size); let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
      const result = uniqueJson(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
      if (path !== '/control/session' && this.#csrf && JSON.stringify(result).includes(this.#csrf)) throw new ControlError('invalid');
      return result;
    } catch (error) { throw error instanceof ControlError ? error : new ControlError(); }
    finally { clearTimeout(timer); controller.abort(); }
  }
  async pair(token?: string): Promise<void> {
    this.retire();
    const owner = this.#generation;
    const v = exact(await this.request('/control/session', 'POST', token === undefined ? {} : { pairing_token: token }), ['schema_version', 'csrf_token', 'expires_at']);
    if (owner !== this.#generation) throw new ControlError('retired');
    if (v.schema_version !== 1 || typeof v.csrf_token !== 'string' || !HEX64.test(v.csrf_token) || typeof v.expires_at !== 'number' || !Number.isFinite(v.expires_at) || v.expires_at <= Date.now() / 1000) throw new ControlError('invalid');
    this.#csrf = v.csrf_token; this.#expires = v.expires_at;
  }
  async revoke(): Promise<void> {
    if (!this.paired) throw new ControlError('unauthorized');
    const owner = this.#generation;
    try {
      const v = exact(await this.request('/control/session', 'DELETE', {}), ['schema_version', 'revoked']);
      if (v.schema_version !== 1 || v.revoked !== true) throw new ControlError('invalid');
    } finally { if (this.#generation === owner) this.retire(); }
  }
  async observe(target?: StartRequest): Promise<ServiceStatus> {
    if (target) { hex(target.request_id, HEX32); hex(target.profile_revision, HEX64); }
    const result = decodeServiceStatus(await this.request('/control/research-services' + (target ? `?request_id=${target.request_id}` : ''), 'GET'));
    if (target && (!result.operation || result.operation.request_id !== target.request_id || result.operation.profile_revision !== target.profile_revision)) throw new ControlError('invalid');
    return result;
  }
  async start(target: StartRequest): Promise<ControlOperation> {
    hex(target.request_id, HEX32); hex(target.profile_revision, HEX64);
    if (!this.paired) throw new ControlError('unauthorized');
    const result = decodeOperation(await this.request('/control/research-services/start', 'POST', { request_id: target.request_id, profile_revision: target.profile_revision }));
    if (result.request_id !== target.request_id || result.profile_revision !== target.profile_revision) throw new ControlError('invalid');
    return result;
  }
}
