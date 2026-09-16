import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRuntime } from './runtime';
import { ApiError } from './api';
import { parseModelSettings, PROVIDERS, type Provider } from './model-settings-contracts';
import { clientSessionScope } from './client-session-scope';

/** Only public metadata belongs in React Query; secret writes bypass mutation caching. */
export function useModelSettings(active = true) {
  const { api, session } = useRuntime();
  const owner = clientSessionScope(api, session);
  const live = useRef<string | null>(owner.id);
  useLayoutEffect(() => {
    live.current = owner.id;
    return () => { live.current = null; };
  }, [owner.id]);
  const status = useQuery({
    queryKey: owner.queryKey,
    queryFn: async () => {
      try {
        if (live.current !== owner.id || !owner.current()) throw new Error();
        const value = await api.get<unknown>('/model-settings');
        if (live.current !== owner.id || !owner.current()) throw new Error();
        return parseModelSettings(value);
      }
      catch (error) { throw new ApiError('Provider settings unavailable', error instanceof ApiError ? error.status : 0); }
    },
    enabled: active && owner.current(),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const [now, setNow] = useState(Date.now);
  const { refetch } = status;
  useEffect(() => {
    if (!active || !session) return;
    const refresh = () => { if (owner.current()) { setNow(Date.now()); void refetch(); } };
    const visible = () => { if (document.visibilityState === 'visible') refresh(); };
    const poll = setInterval(refresh, 30_000);
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', visible);
    return () => {
      clearInterval(poll);
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [active, owner.id, refetch]);
  useEffect(() => {
    const expiry = status.data?.expires_at;
    if (!active || !expiry) return;
    const timer = setTimeout(() => { if (owner.current()) { setNow(Date.now()); void refetch(); } },
      Math.min(Math.max(0, expiry * 1000 - Date.now()), 2_147_483_647));
    return () => clearTimeout(timer);
  }, [active, owner.id, status.data?.expires_at, refetch]);
  const expired = status.data?.source === 'session' && (status.data.expires_at ?? 0) * 1000 <= now;
  // Legacy adapters may not expose this endpoint. Once metadata exists, fail closed on stale/error state.
  const generationAvailable = status.data ? !!session && status.data.configured && !expired && !status.isError
    : status.error instanceof ApiError && status.error.status === 404 ? undefined : false;
  return { api, session, owner, status, expired, generationAvailable, credentialRef: status.data?.credential_ref };
}

export function ModelSettings({ settings }: { settings: ReturnType<typeof useModelSettings> }) {
  const { api, session, owner, status, expired } = settings;
  const password = useRef<HTMLInputElement>(null);
  const [provider, setProvider] = useState<Provider>('openai');
  const [model, setModel] = useState('');
  const [ttlMinutes, setTtlMinutes] = useState<number | null>(30);
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const lifetime = useRef(0);
  const sending = useRef(false);
  useLayoutEffect(() => {
    lifetime.current++;
    sending.current = false;
    setPending(false);
    setFailed(false);
    return () => { lifetime.current++; };
  }, [owner.id]);
  function clearEntry() {
    if (password.current) password.current.value = '';
    setConsent(false);
  }
  useLayoutEffect(() => {
    const input = password.current;
    clearEntry();
    window.addEventListener('pagehide', clearEntry);
    return () => {
      // Capture the node: React detaches refs before passive unmount cleanup.
      if (input) input.value = '';
      window.removeEventListener('pagehide', clearEntry);
    };
  }, [owner.id, status.data?.credential_ref, status.data?.session_keys_allowed, status.isError, expired]);
  async function forget() {
    clearEntry();
    if (!owner.current() || sending.current) return;
    const operation = lifetime.current;
    const generation = api.sessionGeneration;
    const current = () => operation === lifetime.current && owner.current();
    // A 401 may expire this very owner before settlement. Clear that form,
    // but never touch a replacement owner or initiate a read under it.
    const settle = () => current() || (operation === lifetime.current && api.session === null
      && api.sessionGeneration === generation + 1);
    sending.current = true;
    setPending(true);
    setFailed(false);
    try {
      await api.mutate('/model-settings', {}, 'DELETE');
      if (!current()) return;
      const result = await status.refetch();
      if (current() && result.isError) setFailed(true);
    } catch {
      if (settle()) setFailed(true);
    } finally {
      if (settle()) {
        sending.current = false;
        clearEntry();
        setPending(false);
      }
    }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    let api_key = password.current?.value ?? '';
    clearEntry();
    if (!owner.current() || sending.current || !consent || status.isError || !status.data?.session_keys_allowed) return;
    if ((ttlMinutes !== null && ![15, 30, 60, 120].includes(ttlMinutes))
      || !/^[\x21-\x7e]{1,256}$/.test(model) || !/^[\x21-\x7e]{16,4096}$/.test(api_key)
      || model.includes(api_key) || provider.includes(api_key)) {
      setFailed(true);
      return;
    }
    setPending(true);
    setFailed(false);
    const operation = lifetime.current;
    const generation = api.sessionGeneration;
    const current = () => operation === lifetime.current && owner.current();
    // A 401 may expire this very owner before settlement. Clear that form,
    // but never touch a replacement owner or initiate a read under it.
    const settle = () => current() || (operation === lifetime.current && api.session === null
      && api.sessionGeneration === generation + 1);
    sending.current = true;
    try {
      const request = api.mutate('/model-settings', { provider, model, api_key, ttl_minutes: ttlMinutes }, 'PUT');
      api_key = ''; // Drop our reference before awaiting; JS strings cannot be reliably zeroized.
      await request;
      if (!current()) return;
      const result = await status.refetch();
      if (current() && result.isError) setFailed(true);
    } catch {
      if (settle()) setFailed(true);
    } finally {
      if (settle()) {
        sending.current = false;
        setPending(false);
        clearEntry();
      }
    }
  }
  return <section className="raw-section" aria-label="Temporary provider settings">
    <h3>Temporary provider settings</h3>
    <p className="hint">For one shared local operator, not isolated user accounts. This session is shared by tabs.
      Timed keys expire after the selected duration or at session expiry, whichever comes first, and are periodically removed from API memory. Nothing is saved by this form in browser storage.
      Memory zeroization and process isolation cannot be guaranteed.</p>
    <p className="notice warning">Forget or replacement invalidates queued references, but generation jobs already running may finish all their bounded model calls.
      Forget may restore the server environment fallback; it cannot retract calls already sent.</p>
    {!session && <p className="muted">Connect a session to manage temporary keys.</p>}
    {status.isError && <p className="notice warning">Provider settings unavailable. Refresh to verify configuration.</p>}
    {status.data?.session_keys_allowed === false && <p className="notice warning">Temporary key entry requires a configured HTTPS or loopback origin.</p>}
    {status.data?.source === 'none' && <p role="status">No provider configured.</p>}
    {status.data?.source === 'server' && <p role="status">Server environment fallback active · {status.data.provider} · {status.data.model}</p>}
    {expired && <p role="status">Temporary key expired. Refresh status or save a new key before generating.</p>}
    {status.data?.source === 'session' && !expired && <p role="status">Temporary key active · {status.data.provider} · {status.data.model}
      {status.data.key_timer_disabled ? ' · No key timer · Current session deadline ' : ' · Expires '}
      {new Date(status.data.expires_at! * 1000).toLocaleString()}</p>}
    <div className="editor-actions">
      <button type="button" disabled={!session || pending || status.isFetching} onClick={() => { clearEntry(); void status.refetch(); }}>Refresh provider status</button>
      {status.data?.source === 'session' && <button type="button" disabled={!session || pending} onClick={() => void forget()}>Forget key</button>}
    </div>
    <form className="model-settings-form" onSubmit={save} autoComplete="off">
      <label>Provider<select aria-label="Provider" disabled={pending} value={provider} onChange={e => { clearEntry(); setProvider(e.target.value as Provider); }}>
        {PROVIDERS.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
      </select></label>
      <label>Provider endpoint<input readOnly value={PROVIDERS.find(p => p.id === provider)!.base_url} /></label>
      <label>Model<input maxLength={256} disabled={pending} value={model} onChange={e => { clearEntry(); setModel(e.target.value); }} autoComplete="off" /></label>
      <label>Key expiration<select aria-label="Key expiration" disabled={pending} value={ttlMinutes ?? 'never'}
        onChange={e => { clearEntry(); setTtlMinutes(e.target.value === 'never' ? null : Number(e.target.value)); }}>
        <option value={15}>15 minutes</option>
        <option value={30}>30 minutes (default)</option>
        <option value={60}>1 hour</option>
        <option value={120}>2 hours</option>
        <option value="never">Never expires</option>
      </select></label>
      <p className="hint">Applies on the next save, capped by session expiry. To change an active key’s deadline, re-enter the key and save again.</p>
      <p className="hint">Never expires disables only the key timer: the key stays in memory and is cleared when the session ends or the API restarts.
        Explicit session activity can extend its session deadline; polling cannot. Longer retention increases exposure; use Forget key when finished.</p>
      <label className="provider-consent"><input type="checkbox" disabled={pending} checked={consent} onChange={e => { clearEntry(); setConsent(e.target.checked); }} />
        I consent to sending this key to the Arena API now. When I click Generate, the selected fixed provider receives the key, prompt, scene,
        asset/task catalogues, USD context and any retrieved graph priors used by that workflow.
        Saving does not test the key or call the provider.</label>
      <p className="hint">Select the provider, model and expiration, then confirm consent before pasting the key. Changing these fields clears the password.</p>
      <label>API key<input maxLength={4096} disabled={pending || !session || status.isError || !status.data?.session_keys_allowed} ref={password} type="password" autoComplete="new-password" /></label>
      <button type="submit" disabled={!session || status.isError || !status.data?.session_keys_allowed || !consent || pending || !model.trim()}>Save temporary key</button>
    </form>
    {failed && <p className="notice error" role="alert">Could not update temporary provider settings. Re-enter the key to try again.</p>}
  </section>;
}
