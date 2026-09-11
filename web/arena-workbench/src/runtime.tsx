import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
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
  const observer = useRef<Observation | null>(null);
  const mounted = useRef(false);
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
  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => api.get<Health>('/health'),
    retry: false,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  async function connect() {
    observer.current?.stop();
    setConnecting(true);
    setStatus('connecting');
    setError('');
    try {
      const next = await api.connect();
      if (!mounted.current) return;
      setSession(next);
      const live = new Observation(api, cache, makePort);
      observer.current = live;
      live.subscribe(() => {
        if (mounted.current && observer.current === live) {
          setStatus(live.status);
          setError(live.error);
        }
      });
      await live.start();
      void health.refetch();
    } catch (e) {
      if (mounted.current) {
        setError(e instanceof Error ? e.message : 'API unavailable');
        setStatus('disconnected');
      }
    } finally {
      if (mounted.current) setConnecting(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    api.onExpired = () => {
      observer.current?.revoke();
      if (mounted.current) {
        setSession(null);
        setStatus('expired');
      }
    };
    void connect();
    const refocus = () => {
      if (document.visibilityState === 'visible' && api.session) void observer.current?.refresh();
    };
    const leaving = () => observer.current?.stop();
    const restored = (event: PageTransitionEvent) => {
      if (event.persisted) setStatus('disconnected');
    };
    document.addEventListener('visibilitychange', refocus);
    window.addEventListener('pagehide', leaving);
    window.addEventListener('pageshow', restored);
    return () => {
      mounted.current = false;
      observer.current?.stop();
      api.onExpired = () => {};
      document.removeEventListener('visibilitychange', refocus);
      window.removeEventListener('pagehide', leaving);
      window.removeEventListener('pageshow', restored);
    };
    // The provider is mounted once per app, never per route. Dependencies are stable app inputs.
  }, [api, cache, makePort]);
  const value: Runtime = {
    api,
    session,
    health: health.data,
    pending,
    status,
    connecting,
    error: storageError || error || (health.error ? health.error.message : ''),
    connect,
    refresh: async () => {
      await observer.current?.refresh();
    },
    revoke: async () => {
      await api.revoke();
    },
  };
  return <RuntimeContext.Provider value={value}>{children}</RuntimeContext.Provider>;
}
