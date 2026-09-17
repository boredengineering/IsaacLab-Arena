import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRuntime } from './runtime';
import { ApiError } from './api';
import { parseModelSettings, parseModelProfile, PROVIDERS, type Provider, type ModelProfile } from './model-settings-contracts';
import { clientSessionScope } from './client-session-scope';

/** Only public metadata belongs in React Query; secret writes bypass mutation caching. */
export function useModelSettings(active = true) {
  const { api, session } = useRuntime();
  const owner = clientSessionScope(api, session);
  const live = useRef<string | null>(owner.id);
  const readLifetime = useRef(0);
  useLayoutEffect(() => {
    live.current = active ? owner.id : null;
    return () => { live.current = null; readLifetime.current++; };
  }, [active, owner.id]);
  const status = useQuery({
    queryKey: owner.queryKey,
    queryFn: async ({ signal }) => {
      const lifetime = readLifetime.current;
      const current = () => !signal.aborted && lifetime === readLifetime.current && live.current === owner.id && owner.current();
      try {
        if (!current()) throw new Error();
        const value = await api.get<unknown>('/model-settings');
        if (!current()) throw new Error();
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
  const [preset, setPreset] = useState('custom');
  const cache = useQueryClient().getQueryCache();
  const entryEpoch = useRef(0);
  const [entryRevision, setEntryRevision] = useState(0);
  const currentMetadata = () => {
    const query = cache.find({ queryKey: owner.queryKey });
    return !!session && owner.current() && query?.state.status === 'success'
      && query.state.fetchStatus === 'idle' && !query.state.isInvalidated && query.state.data === status.data;
  };
  const metadataCurrent = currentMetadata();
  const profiles = metadataCurrent ? status.data?.profiles : undefined;
  const selectedProfile = profiles?.find(p => p.id === preset) ?? profiles?.find(p => p.origin !== 'user_defined' && p.provider === provider && p.model === model);
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
    setEntryRevision(++entryEpoch.current);
    if (password.current) password.current.value = '';
    setConsent(false);
  }
  useLayoutEffect(() => {
    // Query notifications precede React commits. Revoke retained handlers even on
    // fetch/invalidate -> identical-data ABA, not just object-identity changes.
    let previous = cache.find({ queryKey: owner.queryKey })?.state.data;
    const retire = () => { clearEntry(); setPreset('custom'); };
    retire();
    return cache.subscribe(event => {
      if (event.query !== cache.find({ queryKey: owner.queryKey }) || event.type !== 'updated') return;
      const changed = previous !== event.query.state.data;
      previous = event.query.state.data;
      if (changed || event.action.type === 'fetch' || event.action.type === 'invalidate' || event.action.type === 'error') retire();
    });
  }, [cache, owner.id]);
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
    if (entryRevision !== entryEpoch.current) return;
    const admitted = currentMetadata();
    let api_key = password.current?.value ?? '';
    clearEntry();
    if (!admitted || sending.current || !consent || !status.data?.session_keys_allowed) return;
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
      const request = api.mutate('/model-settings', { provider, model, api_key, ttl_minutes: ttlMinutes,
        ...(preset !== 'custom' && status.data.profile_catalogue_version === 'harness-model-profiles/v2' ? { profile_id: preset } : {}) }, 'PUT');
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
    {metadataCurrent && status.data?.source === 'none' && <p role="status">No provider configured.</p>}
    {metadataCurrent && status.data?.source === 'server' && <p role="status">Server environment fallback active · {status.data.provider} · {status.data.model}</p>}
    {expired && <p role="status">Temporary key expired. Refresh status or save a new key before generating.</p>}
    {metadataCurrent && status.data?.source === 'session' && !expired && <p role="status">Temporary key active · {status.data.provider} · {status.data.model}
      {status.data.key_timer_disabled ? ' · No key timer · Current session deadline ' : ' · Expires '}
      {new Date(status.data.expires_at! * 1000).toLocaleString()}</p>}
    {metadataCurrent && status.data?.configured && !expired && <p role="status">Credential configured · not tested.
      {status.data.effective_profile?.support === 'documented'
        ? ' Effective profile: documented adapter profile · not live verified.'
        : ' Effective profile: compatibility unverified.'}</p>}
    <p className="hint">Live structured-output test: not yet run · unavailable. Saving credentials is not a provider test.</p>
    <div className="editor-actions">
      <button type="button" disabled={!session || pending || status.isFetching} onClick={() => { clearEntry(); void status.refetch(); }}>Refresh provider status</button>
      {status.data?.source === 'session' && <button type="button" disabled={!session || pending} onClick={() => void forget()}>Forget key</button>}
    </div>
    <AddModelProfile key={owner.id} settings={settings} disabled={pending || !metadataCurrent || status.data?.profile_creation !== 'create-only/v1'}
      admitted={() => entryRevision === entryEpoch.current && currentMetadata() && !sending.current && status.data?.profile_creation === 'create-only/v1'}
      retireEntry={clearEntry} />
    <form className="model-settings-form" onSubmit={save} autoComplete="off">
      <label>Model profile<select aria-label="Model profile" disabled={pending || !profiles?.length} value={preset}
        onChange={e => {
          if (entryRevision !== entryEpoch.current) return;
          const admitted = currentMetadata();
          clearEntry();
          if (!admitted) return;
          const profile = profiles?.find(p => p.id === e.target.value);
          setPreset(profile?.id ?? 'custom');
          if (profile) { setProvider(profile.provider); setModel(profile.model); }
        }}>
        <option value="custom">Custom model (enter exact model ID)</option>
        {profiles?.map(p => <option key={p.id} value={p.id}>{p.origin === 'user_defined' ? `${p.provider} · ${p.model} · ${p.id} · unverified` : p.model}</option>)}
      </select></label>
      {!profiles && <p className="hint">Profile presets unavailable · compatibility unverified. Custom model entry remains available when credential settings can be read.</p>}
      {selectedProfile ? <div className="hint" aria-label="Selected model compatibility">
        <p>{selectedProfile.origin === 'user_defined' ? 'User-defined profile · unverified' : 'Documented adapter profile · not live verified'}. Applies on the next explicit save, not the active credential.</p>
        <p>Chat Completions · structured output: {selectedProfile.request_policy.structured_output} · Temperature: {selectedProfile.request_policy.temperature_mode} ·
          Token limit parameter: {selectedProfile.request_policy.token_limit_parameter}
          {selectedProfile.request_policy.token_limit_parameter === 'max_completion_tokens'
            ? ' (completion budget includes reasoning tokens, not only visible output).'
            : ' (output token budget; not a context-window size).'}
          {' '}Store: {selectedProfile.request_policy.store === false ? 'false' : 'omitted (provider default)'}.</p>
        <p>These are adapter parameters, not verified model access, context limits or live structured-output results.</p>
        {selectedProfile.documentation_urls.map((url, index) => <a key={url} href={url} target="_blank" rel="noreferrer noopener">Profile documentation {index + 1}</a>)}
      </div> : model && <p className="hint">Custom profile · unverified. No documented adapter match is available; model access and structured-output compatibility are not checked.</p>}
      <label>Provider<select aria-label="Provider" disabled={pending} value={provider} onChange={e => { clearEntry(); setPreset('custom'); setProvider(e.target.value as Provider); }}>
        {PROVIDERS.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
      </select></label>
      <label>Provider endpoint<input readOnly value={PROVIDERS.find(p => p.id === provider)!.base_url} /></label>
      <label>Model<input maxLength={256} disabled={pending} value={model} onChange={e => { clearEntry(); setPreset('custom'); setModel(e.target.value); }} autoComplete="off" /></label>
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
      <label>API key<input maxLength={4096} disabled={pending || !metadataCurrent || !status.data?.session_keys_allowed} ref={password} type="password" autoComplete="new-password" /></label>
      <button type="submit" disabled={!metadataCurrent || !status.data?.session_keys_allowed || !consent || pending || !model.trim()}>Save temporary key</button>
    </form>
    {failed && <p className="notice error" role="alert">Could not update temporary provider settings. Re-enter the key to try again.</p>}
  </section>;
}

function AddModelProfile({ settings, disabled, admitted, retireEntry }: {
  settings: ReturnType<typeof useModelSettings>; disabled: boolean; admitted: () => boolean; retireEntry: () => void;
}) {
  const { api, owner, status } = settings;
  const [open, setOpen] = useState(false);
  const [id, setId] = useState('');
  const [provider, setProvider] = useState<Provider>('openai');
  const [model, setModel] = useState('');
  const [policy, setPolicy] = useState<ModelProfile['request_policy']>({ api: 'chat_completions', temperature_mode: 'configured',
    token_limit_parameter: 'max_tokens', structured_output: 'json_schema', multimodal_output: 'json_object', store: null });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const serial = useRef(0);
  const [revision, setRevision] = useState(0);
  const lifetime = useRef(0);
  const sending = useRef(false);
  const mounted = useRef(false);
  useLayoutEffect(() => { mounted.current = true; lifetime.current++; return () => { mounted.current = false; lifetime.current++; }; }, []);
  function change(action: () => void) {
    if (!mounted.current || !owner.current() || sending.current) return;
    setRevision(++serial.current); setNotice(''); action();
  }
  async function create(event: FormEvent) {
    event.preventDefault();
    if (!mounted.current || revision !== serial.current || !admitted() || sending.current) return;
    const endpoint = PROVIDERS.find(p => p.id === provider)!.base_url;
    let expected: ModelProfile;
    try {
      expected = parseModelProfile({ id, revision: 1, provider, model, endpoint, origin: 'user_defined',
        support: 'unverified', verification: 'not_checked', documentation_urls: [], request_policy: policy });
      if (id === 'custom' || status.data?.profiles?.some(p => p.id === id)) throw new Error();
    } catch { setNotice('Invalid or existing profile identity. Choose a new bounded ID and literal model.'); return; }
    const body = { provider, model, request_policy: expected.request_policy };
    const operation = lifetime.current;
    const current = () => operation === lifetime.current && owner.current();
    sending.current = true; setBusy(true); setNotice(''); retireEntry();
    try {
      const saved = parseModelProfile(await api.mutate(`/model-settings/profiles/${encodeURIComponent(id)}`, body, 'PUT'));
      if (!current()) return;
      // Readback is authoritative; a successful PUT alone never enables selection.
      const result = await status.refetch();
      if (!current()) return;
      const read = result.data?.profiles?.find(p => p.id === expected.id);
      const equal = (a: ModelProfile, b: ModelProfile) => JSON.stringify(a) === JSON.stringify(b);
      if (result.isError || !read || !equal(saved, expected) || !equal(read, expected)) throw new Error();
      setOpen(false); setNotice('Profile saved and read back. Select it explicitly, then save a key separately.');
    } catch {
      if (current()) setNotice('Profile save or readback unconfirmed. Refresh the catalogue; retry the identical ID and policy, never replace an existing profile.');
    } finally {
      if (current()) { sending.current = false; setBusy(false); }
    }
  }
  return <div className="model-profile-creation">
    <p className="hint">Profiles persist in this workspace across API restarts and are shared by local sessions. Profiles contain no credentials.
      Keys stay memory-only. Adding a profile does not contact a provider, verify compatibility, or activate it. Profiles cannot be edited or deleted here.</p>
    <button type="button" disabled={disabled || busy} onClick={() => {
      if (revision !== serial.current || !admitted()) return;
      change(() => setOpen(true)); retireEntry();
    }}>Add model profile</button>
    {open && <form className="model-settings-form" aria-label="Add model profile form" onSubmit={create} autoComplete="off">
      <fieldset disabled={disabled || busy} style={{ minWidth: 0 }}>
        <legend>Unverified request policy · Chat Completions</legend>
        <label>New profile ID<input aria-label="New profile ID" maxLength={64} value={id} onChange={e => change(() => setId(e.target.value))} /></label>
        <label>New profile provider<select aria-label="New profile provider" value={provider} onChange={e => change(() => setProvider(e.target.value as Provider))}>
          {PROVIDERS.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select></label>
        <label>New profile model literal<input aria-label="New profile model literal" maxLength={256} value={model} onChange={e => change(() => setModel(e.target.value))} /></label>
        {([
          ['temperature_mode', 'Profile temperature', ['configured', 'omitted']],
          ['token_limit_parameter', 'Profile token limit parameter', ['max_tokens', 'max_completion_tokens']],
          ['structured_output', 'Profile structured output', ['json_schema', 'json_object', 'omitted']],
          ['multimodal_output', 'Profile multimodal output', ['json_object', 'omitted']],
        ] as const).map(([field, label, options]) => <label key={field}>{label}<select aria-label={label} value={policy[field]}
          onChange={e => change(() => setPolicy(p => ({ ...p, [field]: e.target.value })))}>
          {options.map(option => <option key={option} value={option}>{option}</option>)}
        </select></label>)}
        <label>Profile store<select aria-label="Profile store" value={policy.store === false ? 'false' : 'omitted'}
          onChange={e => change(() => setPolicy(p => ({ ...p, store: e.target.value === 'false' ? false : null })))}>
          <option value="omitted">omitted (provider default)</option><option value="false">false</option>
        </select></label>
        <p className="hint">Configured temperature uses the workflow's numeric temperature. JSON object and omitted modes use explicit schema instructions and local validation, not provider-side schema enforcement. Store false is not a guarantee of zero provider retention.</p>
        <button type="submit">Save new profile</button>
        <button type="button" onClick={() => { if (revision === serial.current && owner.current()) change(() => setOpen(false)); }}>Cancel adding profile</button>
      </fieldset>
    </form>}
    {notice && <p role="status">{notice}</p>}
  </div>;
}
