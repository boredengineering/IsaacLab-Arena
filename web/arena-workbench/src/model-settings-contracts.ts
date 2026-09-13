export const PROVIDERS = [
  { id: 'openai', label: 'OpenAI', base_url: 'https://api.openai.com/v1' },
  { id: 'gemini', label: 'Gemini', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/' },
  { id: 'openrouter', label: 'OpenRouter', base_url: 'https://openrouter.ai/api/v1' },
  { id: 'nvidia', label: 'NVIDIA', base_url: 'https://integrate.api.nvidia.com/v1' },
] as const;
/** Project responses before caching; unexpected fields never enter public state. */
export function parseModelSettings(value: unknown): ModelSettingsStatus {
  const fail = () => { throw new Error('Provider settings unavailable'); };
  if (!value || typeof value !== 'object') return fail();
  const v = value as Record<string, unknown>;
  const text = (s: unknown): s is string => typeof s === 'string' && s.length > 0 && s.length <= 4096;
  if (!Array.isArray(v.providers) || v.providers.length !== PROVIDERS.length
    || !PROVIDERS.every(p => (v.providers as unknown[]).some(candidate => {
      if (!candidate || typeof candidate !== 'object') return false;
      const item = candidate as Record<string, unknown>;
      return item.id === p.id && item.base_url === p.base_url && typeof item.label === 'string';
    })) || typeof v.configured !== 'boolean' || typeof v.session_keys_allowed !== 'boolean'
    || !['none', 'session', 'server'].includes(String(v.source))) return fail();
  if (v.source === 'none') {
    if (v.configured || v.provider !== null || v.model !== null) return fail();
  } else if (!v.configured || !text(v.provider) || !text(v.model)) return fail();
  if (v.source === 'session') {
    if (!PROVIDERS.some(p => p.id === v.provider) || !text(v.credential_ref)
      || typeof v.expires_at !== 'number' || !Number.isFinite(v.expires_at) || v.expires_at <= 0) return fail();
  } else if (v.credential_ref !== null || v.expires_at !== null) return fail();
  return {
    providers: PROVIDERS.map(p => ({ ...p })), configured: v.configured, source: v.source as ModelSettingsStatus['source'],
    provider: v.provider as string | null, model: v.model as string | null,
    expires_at: v.expires_at as number | null, credential_ref: v.credential_ref as string | null,
    session_keys_allowed: v.session_keys_allowed,
  };
}
export type Provider = typeof PROVIDERS[number]['id'];
export interface ModelSettingsStatus {
  providers: { id: Provider; label: string; base_url: string }[];
  configured: boolean;
  source: 'session' | 'server' | 'none';
  provider: string | null;
  model: string | null;
  expires_at: number | null;
  credential_ref: string | null;
  session_keys_allowed: boolean;
}
