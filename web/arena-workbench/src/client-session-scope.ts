import type { ApiClient } from './api';

// Cache identity must never contain CSRF material or conflate different clients.
const identities = new WeakMap<object, number>();
let nextIdentity = 0;
function identity(value: object) {
  let id = identities.get(value);
  if (id === undefined) { id = ++nextIdentity; identities.set(value, id); }
  return id;
}

/** Capture authority, not a session object's activity-updated deadline. */
export function clientSessionScope(api: ApiClient, session: { session_id: string } | null) {
  const generation = api.sessionGeneration;
  const captured = api.session;
  // Structural adapters without generation support must preserve session identity.
  const epoch = generation ?? (captured ? identity(captured) : null);
  const queryKey = ['model-settings', identity(api), epoch, session?.session_id ?? null] as const;
  return {
    id: JSON.stringify(queryKey),
    queryKey,
    current: () => !!session && api.session?.session_id === session.session_id
      && (generation === undefined ? api.session === captured : api.sessionGeneration === generation),
  };
}
