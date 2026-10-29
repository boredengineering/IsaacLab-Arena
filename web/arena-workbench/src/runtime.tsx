import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiClient, PendingJob } from './api';
import type { Health, Session } from './contracts';
import { Observation, sharedPort, type ObservationPort } from './observation';
import type { ConnectionStatus } from './stream-hub';
interface Runtime {
  api: ApiClient;
  session: Session | null;
  health?: Health;
  pending?: PendingJob;
  status: ConnectionStatus;
  error: string;
  connecting: boolean;
  connect(): Promise<void>;
  refresh(): Promise<void>;
  revoke(): Promise<void>;
}
const RuntimeContext = createContext<Runtime | null>(null);
export function useRuntime() {
  const value = useContext(RuntimeContext);
  if (!value) throw new Error('Missing runtime');
  return value;
}
export function RuntimeProvider({
  api,
  makePort = sharedPort,
  children,
}: {
  api: ApiClient;
  makePort?: () => ObservationPort | null;
  children: ReactNode;
}) {
  const cache = useQueryClient();
  // Retained callbacks from an earlier client must not target a replacement owner.
  const controls = useMemo(() => ({
    connect: async () => {},
    refresh: async () => {},
    revoke: async () => {},
  }), [api, cache, makePort]);
  const [session, setSession] = useState<Session | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>('connecting');
  const [error, setError] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [{ pending, storageError }] = useState(() => {
    try {
      return { pending: new PendingJob(sessionStorage), storageError: '' };
    } catch (e) {
      return { pending: undefined, storageError: String(e) };
    }
  });
  // Health can precede a session: bind it to the client/provider lifetime, not
  // activity-updated session metadata. Use a primitive, never a hashed client object.
  const healthOwner = useMemo(() => crypto.randomUUID(), [api, cache, makePort]);
  const health = useQuery({
    queryKey: ['health', healthOwner],
    queryFn: async ({ signal }) => {
      // Consuming the query signal retires pending reads with their observer.
      // ApiClient owns its wire timeout; fence settlement even if transport finishes late.
      signal.throwIfAborted();
      try {
        return await api.get<Health>('/health');
      } finally {
        signal.throwIfAborted();
      }
    },
    retry: false,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  useEffect(() => {
    // Each effect setup owns an irreversible lifetime, including StrictMode replay.
    let alive = true;
    let observer: Observation | undefined;
    type Attempt = { phase: 'session' | 'observation'; promise?: Promise<void> };
    let attempt: Attempt | undefined;
    const retire = () => {
      attempt = undefined;
      observer?.stop();
      observer = undefined;
    };
    function connect(): Promise<void> {
      if (!alive) return Promise.resolve();
      // Share session establishment, but allow explicit reconnect during a stuck snapshot.
      if (attempt?.phase === 'session') return attempt.promise!;
      retire();
      const current: Attempt = { phase: 'session' };
      attempt = current;
      const isCurrent = () => alive && attempt === current;
      setConnecting(true);
      setSession(null);
      setStatus('connecting');
      setError('');
      current.promise = (async () => {
        try {
          const next = await api.connect();
          if (!isCurrent()) return;
          current.phase = 'observation';
          setSession(next);
          const live = new Observation(api, cache, makePort);
          observer = live;
          live.subscribe(() => {
            if (isCurrent() && observer === live) {
              setStatus(live.status);
              setError(live.error);
            }
          });
          await live.start();
          if (!isCurrent()) return;
          void health.refetch();
        } catch (e) {
          if (isCurrent()) {
            observer?.stop();
            observer = undefined;
            setError(e instanceof Error ? e.message : 'API unavailable');
            setStatus('disconnected');
          }
        } finally {
          if (isCurrent()) setConnecting(false);
        }
      })();
      // A failed session attempt may be retried; a live observer retains its fence.
      void current.promise.then(() => {
        if (isCurrent() && current.phase === 'session') attempt = undefined;
      });
      return current.promise;
    }
    const expired = () => {
      if (!alive) return;
      observer?.revoke();
      retire();
      setSession(null);
      setStatus('expired');
      setConnecting(false);
    };
    api.onExpired = expired;
    controls.connect = connect;
    controls.refresh = async () => { if (alive) await observer?.refresh(); };
    controls.revoke = async () => { if (alive) await api.revoke(); };
    void connect();
    const refocus = () => {
      if (document.visibilityState === 'visible' && api.session) void observer?.refresh();
    };
    const leaving = () => { retire(); setConnecting(false); };
    const restored = (event: PageTransitionEvent) => {
      if (event.persisted) setStatus('disconnected');
    };
    document.addEventListener('visibilitychange', refocus);
    window.addEventListener('pagehide', leaving);
    window.addEventListener('pageshow', restored);
    return () => {
      alive = false;
      retire();
      if (api.onExpired === expired) api.onExpired = () => {};
      document.removeEventListener('visibilitychange', refocus);
      window.removeEventListener('pagehide', leaving);
      window.removeEventListener('pageshow', restored);
    };
  }, [api, cache, makePort, controls]);
  const value: Runtime = {
    api,
    session,
    health: health.data,
    pending,
    status,
    connecting,
    error: storageError || error || (health.error ? health.error.message : ''),
    connect: () => controls.connect(),
    refresh: () => controls.refresh(),
    revoke: () => controls.revoke(),
  };
  return <RuntimeContext.Provider value={value}>{children}</RuntimeContext.Provider>;
}
