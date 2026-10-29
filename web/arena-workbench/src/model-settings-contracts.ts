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
  if (v.key_timer_disabled !== undefined && typeof v.key_timer_disabled !== 'boolean') return fail();
  if (v.key_timer_disabled === true && v.source !== 'session') return fail();
  return {
    providers: PROVIDERS.map(p => ({ ...p })), configured: v.configured, source: v.source as ModelSettingsStatus['source'],
    provider: v.provider as string | null, model: v.model as string | null,
    expires_at: v.expires_at as number | null, credential_ref: v.credential_ref as string | null,
    session_keys_allowed: v.session_keys_allowed,
    key_timer_disabled: v.key_timer_disabled === true,
    ...parseProfiles(v),
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
  key_timer_disabled?: boolean;
  profile_catalogue_version?: 'harness-model-profiles/v1' | 'harness-model-profiles/v2';
  profile_creation?: 'create-only/v1';
  profiles?: ModelProfile[];
  effective_profile?: { id: string | null; support: 'documented' | 'unverified'; verification: 'not_checked' } | null;
  profile_metadata_invalid?: true;
}

export interface ModelProfile {
  id: string;
  revision: 1;
  provider: Provider;
  model: string;
  endpoint: string;
  support: 'documented' | 'unverified';
  origin?: 'builtin' | 'user_defined';
  verification?: 'not_checked';
  documentation_urls: string[];
  request_policy: {
    api: 'chat_completions'; structured_output: 'json_schema' | 'json_object' | 'omitted';
    multimodal_output?: 'json_object' | 'omitted';
    temperature_mode: 'configured' | 'omitted';
    token_limit_parameter: 'max_tokens' | 'max_completion_tokens'; store: null | false;
  };
}

/** Versioned public labels, not model-name heuristics or client-side adapter policy. */
function parseProfiles(v: Record<string, unknown>): Partial<ModelSettingsStatus> {
  if (v.profile_catalogue_version === 'harness-model-profiles/v2') return parseProfilesV2(v);
  if (!['profile_catalogue_version', 'profiles', 'effective_profile'].some(key => key in v)) return {};
  const invalid = { profile_metadata_invalid: true } as const;
  const object = (value: unknown): value is Record<string, unknown> =>
    !!value && typeof value === 'object' && !Array.isArray(value);
  if (v.profile_catalogue_version !== 'harness-model-profiles/v1'
    || !Array.isArray(v.profiles) || v.profiles.length > 2) return invalid;
  const identities = {
    'openai-gpt-4.1': { model: 'gpt-4.1', temperature_mode: 'configured', token_limit_parameter: 'max_tokens', store: null },
    'openai-gpt-6-astra': { model: 'gpt-6-astra', temperature_mode: 'omitted', token_limit_parameter: 'max_completion_tokens', store: false },
  } as const;
  const profiles: ModelProfile[] = [];
  for (const item of v.profiles) {
    if (!object(item) || typeof item.id !== 'string' || !Object.hasOwn(identities, item.id)) return invalid;
    const id = item.id as keyof typeof identities;
    const policy = item.request_policy;
    if (profiles.some(p => p.id === id) || item.model !== identities[id].model || item.provider !== 'openai'
      || item.revision !== 1 || item.endpoint !== PROVIDERS[0].base_url || item.support !== 'documented'
      || !Array.isArray(item.documentation_urls) || !item.documentation_urls.length || item.documentation_urls.length > 8
      || !item.documentation_urls.every(url => typeof url === 'string' && url.length <= 2048
        && /^https:\/\/(?:platform\.openai\.com|developers\.openai\.com|openai\.com)\/[A-Za-z0-9/_.,#?=&%-]*$/.test(url))
      || !object(policy) || policy.api !== 'chat_completions' || policy.structured_output !== 'json_schema'
      || policy.temperature_mode !== identities[id].temperature_mode
      || policy.token_limit_parameter !== identities[id].token_limit_parameter
      || policy.store !== identities[id].store) return invalid;
    profiles.push({ id, revision: 1, provider: 'openai', model: identities[id].model, endpoint: PROVIDERS[0].base_url,
      support: 'documented', documentation_urls: [...item.documentation_urls],
      request_policy: { api: 'chat_completions', structured_output: 'json_schema',
        temperature_mode: policy.temperature_mode as ModelProfile['request_policy']['temperature_mode'],
        token_limit_parameter: policy.token_limit_parameter as ModelProfile['request_policy']['token_limit_parameter'],
        store: identities[id].store } });
  }
  const effective = v.effective_profile;
  if (v.configured === false) {
    if (effective !== null) return invalid;
  } else {
    if (!object(effective) || effective.verification !== 'not_checked') return invalid;
    if (effective.support === 'documented') {
      if (!profiles.some(p => p.id === effective.id && p.provider === v.provider && p.model === v.model)) return invalid;
    } else if (effective.support !== 'unverified' || effective.id !== null) return invalid;
  }
  return { profile_catalogue_version: 'harness-model-profiles/v1', profiles,
    effective_profile: effective === null ? null : {
      id: (effective as Record<string, unknown>).id as string | null,
      support: (effective as Record<string, unknown>).support as 'documented' | 'unverified', verification: 'not_checked',
    } };
}

const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const exact = (v: Record<string, unknown>, fields: string[]) => Object.keys(v).length === fields.length && fields.every(k => Object.hasOwn(v, k));
/** Strict v2 format. Legacy v1 intentionally remains a projecting decoder. */
export function parseModelProfile(value: unknown): ModelProfile {
  const fail = (): never => { throw new Error('Model profile unavailable'); };
  if (!object(value) || !exact(value, ['id', 'revision', 'provider', 'model', 'endpoint', 'origin', 'support', 'verification', 'documentation_urls', 'request_policy'])
    || typeof value.id !== 'string' || value.id === 'custom' || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(value.id)
    || typeof value.model !== 'string' || !/^[\x21-\x7e]{1,256}$/.test(value.model)
    || value.revision !== 1 || value.verification !== 'not_checked'
    || !PROVIDERS.some(p => p.id === value.provider && p.base_url === value.endpoint)) return fail();
  const policy = value.request_policy;
  if (!object(policy) || !exact(policy, ['api', 'temperature_mode', 'token_limit_parameter', 'structured_output', 'multimodal_output', 'store'])
    || policy.api !== 'chat_completions' || !['configured', 'omitted'].includes(String(policy.temperature_mode))
    || !['max_tokens', 'max_completion_tokens'].includes(String(policy.token_limit_parameter))
    || !['json_schema', 'json_object', 'omitted'].includes(String(policy.structured_output))
    || !['json_object', 'omitted'].includes(String(policy.multimodal_output))
    || (policy.store !== null && policy.store !== false)
    || Object.entries(policy).some(([k, v]) => k !== 'store' && typeof v !== 'string')) return fail();
  const builtin = ['openai-gpt-4.1', 'openai-gpt-6-astra'].includes(value.id);
  if (builtin) {
    if (value.origin !== 'builtin' || value.support !== 'documented' || policy.multimodal_output !== 'json_object') return fail();
    const legacy = parseProfiles({ profile_catalogue_version: 'harness-model-profiles/v1', profiles: [value], configured: false, effective_profile: null });
    if (legacy.profile_metadata_invalid) return fail();
  } else if (value.origin !== 'user_defined' || value.support !== 'unverified'
    || !Array.isArray(value.documentation_urls) || value.documentation_urls.length !== 0) return fail();
  return { id: value.id, revision: 1, provider: value.provider as Provider, model: value.model, endpoint: value.endpoint as string,
    origin: value.origin as 'builtin' | 'user_defined', support: value.support as 'documented' | 'unverified', verification: 'not_checked',
    documentation_urls: [...value.documentation_urls as string[]], request_policy: { api: 'chat_completions',
      temperature_mode: policy.temperature_mode as 'configured' | 'omitted',
      token_limit_parameter: policy.token_limit_parameter as 'max_tokens' | 'max_completion_tokens',
      structured_output: policy.structured_output as 'json_schema' | 'json_object' | 'omitted',
      multimodal_output: policy.multimodal_output as 'json_object' | 'omitted', store: policy.store } };
}
function parseProfilesV2(v: Record<string, unknown>): Partial<ModelSettingsStatus> {
  const invalid = { profile_metadata_invalid: true } as const;
  try {
    if (!Array.isArray(v.profiles) || v.profiles.length > 66) return invalid;
    const profiles = v.profiles.map(parseModelProfile);
    if (new Set(profiles.map(p => p.id)).size !== profiles.length || profiles.filter(p => p.origin === 'user_defined').length > 64) return invalid;
    const effective = v.effective_profile;
    if (v.configured === false) { if (effective !== null) return invalid; }
    else {
      if (!object(effective) || !exact(effective, ['id', 'support', 'verification']) || effective.verification !== 'not_checked') return invalid;
      if (effective.id === null) { if (effective.support !== 'unverified') return invalid; }
      else if (!profiles.some(p => p.id === effective.id && p.model === v.model && p.provider === v.provider && p.support === effective.support)) return invalid;
    }
    return { profile_catalogue_version: 'harness-model-profiles/v2', profiles,
      effective_profile: effective as ModelSettingsStatus['effective_profile'],
      ...(v.profile_creation === 'create-only/v1' ? { profile_creation: 'create-only/v1' as const } : {}) };
  } catch { return invalid; }
}
