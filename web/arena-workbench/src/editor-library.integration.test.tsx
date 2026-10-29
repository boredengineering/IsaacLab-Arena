import { createHash, webcrypto } from 'node:crypto';
import { StrictMode } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { EditorView as CodeMirrorView } from '@codemirror/view';
import { beforeEach, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { createMemoryHistory } from '@tanstack/react-router';
import { App } from './app';
import { ApiClient } from './api';
import { PROVIDERS } from './model-settings-contracts';
import { editorSaveRequestHash, type EditorSaveRequest } from './editor-revision-contracts';
import * as nativePreferences from './library-preferences-native';
import type { DraftController } from './draft-controller';
import { decodeLibraryEnvelope } from './library-preferences';

// Serial adapter fixture across App mounts, not native IndexedDB acceptance.
function persistentPreferenceFixture() {
  let stored: unknown;
  let tail = Promise.resolve();
  vi.spyOn(nativePreferences, 'createNativeLibraryAdapter').mockImplementation(() => ({
    open: async () => {}, close() {},
    transaction(mode, mutate) {
      const operation = tail.then(() => {
        const next = mutate(structuredClone(stored));
        if (mode === 'readwrite') stored = structuredClone(next);
        return next;
      });
      tail = operation.then(() => {}, () => {});
      return operation;
    },
  }));
  return () => decodeLibraryEnvelope(stored)?.preferences;
}

const hash = (text: string) => createHash('sha256').update(text).digest('hex');
const source = 'env_name: fixture\n';
const edited = 'env_name: edited\n';
const viewId = '1'.repeat(32), revisionId = '2'.repeat(32), reopenedView = '3'.repeat(32);
const revisionSource = `editor-revision:${revisionId}`;
const canonical = 'a'.repeat(64);
const file = {id: 'fixture', kind: 'discovered_file', name: 'Fixture file', source: 'tests/fixture.yaml'};
const revisionRow = {id: revisionSource, kind: 'editor_revision', name: 'Saved fixture', source: revisionSource, revision_id: revisionId, source_hash: hash(edited), canonical_hash: canonical};
const wire = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status});
const session = {session_id: 'integration-session', csrf_token: 'test-token', expires_at: 9999999999};
async function makeReceipt(request: EditorSaveRequest) {
  return {schema_version: 1, state: 'committed', idempotency_key: request.idempotency_key, request_sha256: await editorSaveRequestHash(request), revision: {revision_id: revisionId, yaml_text: request.yaml_text, source_hash: hash(request.yaml_text), canonical_hash: canonical, download_url: `/api/editor/revisions/${revisionId}/download`, open_source: {kind: 'editor_revision', id: revisionSource}}};
}
const projection = (text: string) => ({valid: true, source_hash: hash(text), canonical_hash: canonical, errors: [], warnings: [], spec: {}, summary: 'Validated fixture', graph: {nodes: [], edges: []}, assets: [], relations: [], reified_relations: [], tasks: []});
function setup(path = '/library', intercept?: (url: string, init?: RequestInit) => Promise<Response> | Response | undefined, durable = true, strict = false) {
  let saved: unknown;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const intercepted = intercept?.(url, init); if (intercepted) return intercepted;
    if (url.endsWith('/sessions') || url.endsWith('/session/activity')) return wire(session);
    if (url.endsWith('/health')) return wire({status: 'ok', capabilities: {diagnostic: false, generation: false, preview: false, durable_editor_save: durable}});
    if (url.endsWith('/workspaces/default')) return wire({id: 'default', name: 'Workspace', jobs: [], event_cursor: 0});
    if (url.endsWith('/model-settings')) return wire({providers: PROVIDERS, configured: false, source: 'none', provider: null, model: null, expires_at: null, credential_ref: null, session_keys_allowed: false});
    if (url === '/api/editor') return wire({default_document_id: 'fixture', documents: saved ? [file, revisionRow] : [file], capabilities: {generation: false, snapshots: false, neo4j: false}, limitations: []});
    if (url === '/api/editor/documents/fixture') return wire({document_id: viewId, source: file.source, source_origin: {kind: file.kind, id: file.id}, yaml_text: source, source_hash: hash(source), validation: projection(source)});
    if (url === `/api/editor/documents/${encodeURIComponent(revisionSource)}`) return wire({document_id: reopenedView, source: revisionSource, source_origin: {kind: 'editor_revision', id: revisionSource}, yaml_text: edited, source_hash: hash(edited), validation: projection(edited)});
    if (url.endsWith('/editor/validate')) return wire(projection(JSON.parse(init!.body as string).yaml_text));
    if (url.includes('/editor/previews/')) return wire({status: 'miss', canonical_hash: canonical, receipt: null});
    if (url === '/api/editor/save') {
      const request = JSON.parse(init!.body as string) as EditorSaveRequest;
      const revision = {revision_id: revisionId, yaml_text: request.yaml_text, source_hash: hash(request.yaml_text), canonical_hash: canonical, download_url: `/api/editor/revisions/${revisionId}/download`, open_source: {kind: 'editor_revision', id: revisionSource}};
      saved = {schema_version: 1, state: 'committed', idempotency_key: request.idempotency_key, request_sha256: await editorSaveRequestHash(request), revision};
      return wire(durable ? saved : revision);
    }
    if (url.startsWith('/api/editor/save-requests/')) return wire(saved);
    return wire({detail: 'No transport fixture for ' + url}, 404);
  });
  const api = new ApiClient(fetcher as typeof fetch);
  const cache = new QueryClient({defaultOptions: {queries: {retry: false, gcTime: 0}, mutations: {retry: false}}});
  const history = createMemoryHistory({initialEntries: [path]});
  const tree = (client = api) => {
    const app = <App api={client} cache={cache} history={history} makePort={() => null} />;
    return strict ? <StrictMode>{app}</StrictMode> : app;
  };
  const mounted = render(tree());
  return {api, cache, fetcher, history, ...mounted, redraw: (client = api) => mounted.rerender(tree(client))};
}
function edit(text = edited) {
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', {name: 'YAML editor'}))!;
  act(() => cm.dispatch({changes: {from: 0, to: cm.state.doc.length, insert: text}}));
}
const text = () => CodeMirrorView.findFromDOM(screen.getByRole('textbox', {name: 'YAML editor'}))!.state.doc.toString();
// Observe the actual mounted confirmation shelf, including while the Library is
// inactive. The legacy localStorage key is no longer a production writer.
const recentIds = () => Array.from(document.querySelectorAll('[aria-label="Recent opens"] button[aria-label]'))
  .map(button => button.getAttribute('aria-label')!.replace(/^Inspect reference /, ''));
async function openFile() {
  fireEvent.click(await screen.findByRole('button', {name: 'Inspect Fixture file'}));
  fireEvent.click(screen.getByRole('button', {name: 'Open source in editor'}));
  await waitFor(() => expect(text()).toBe(source));
}
beforeEach(() => {sessionStorage.clear(); localStorage.clear(); vi.stubGlobal('crypto', webcrypto);});

it('exports the verified durable revision from the mounted V7 App without opening or replacing the draft', async () => {
  let release!: (response: Response) => void;
  const fixture = setup('/workspaces/default?layout=v7', (url, init) => {
    if (url.startsWith('/api/editor/save-requests/')) return new Promise<Response>(resolve => {release = resolve;});
    if (url === '/api/editor/validate' && JSON.parse(String(init?.body)).yaml_text === 'invalid: [') return wire({...projection('invalid: ['), valid: false, errors: ['Invalid YAML']});
  });
  await waitFor(() => expect(text()).toBe(source));
  edit(); fireEvent.click(screen.getByRole('button', {name: 'Validate schema'}));
  await waitFor(() => expect(screen.getByRole('button', {name: 'Save durable revision'})).toBeEnabled());
  expect(screen.queryByRole('button', {name: 'Save revision'})).not.toBeInTheDocument();
  expect(screen.queryByRole('link', {name: 'Export flattened YAML'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: 'Save durable revision'}));
  await waitFor(() => expect(release).toBeTypeOf('function'));
  expect(screen.queryByRole('link', {name: 'Export flattened YAML'})).not.toBeInTheDocument();
  const request = JSON.parse(String(fixture.fetcher.mock.calls.find(([url]) => url === '/api/editor/save')![1]?.body));
  await act(async () => release(wire(await makeReceipt(request))));
  const link = await screen.findByRole('link', {name: 'Export flattened YAML'});
  expect(link).toHaveAttribute('href', `/api/editor/revisions/${revisionId}/download`);
  expect(link).toHaveAttribute('download');
  expect(within(screen.getByRole('region', {name: 'Durable editor save'})).getByRole('link', {name: 'Export flattened YAML'})).toBe(link);
  expect(text()).toBe(edited);
  expect(screen.getByLabelText('Document')).toHaveValue('fixture');
  expect(screen.getByRole('button', {name: 'Download current YAML'})).toBeEnabled();
  edit('invalid: [');
  fireEvent.click(screen.getByRole('button', {name: 'Validate schema'}));
  await screen.findByText('Invalid YAML');
  expect(screen.getByRole('button', {name: 'Save durable revision'})).toBeDisabled();
  expect(screen.getByRole('link', {name: 'Export flattened YAML'})).toHaveAttribute('href', `/api/editor/revisions/${revisionId}/download`);
  expect(screen.getByText('Saved frozen revision — current draft has unsaved changes')).toBeVisible();
  const blobs: Blob[] = [];
  vi.spyOn(URL, 'createObjectURL').mockImplementation(blob => {blobs.push(blob as Blob); return 'blob:current-draft';});
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  fireEvent.click(screen.getByRole('button', {name: 'Download current YAML'}));
  expect(blobs).toHaveLength(1);
  const downloaded = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsText(blobs[0]);
  });
  expect(downloaded).toBe('invalid: [');
  expect(request.yaml_text).toBe(edited);
  expect(fixture.fetcher.mock.calls.filter(([url]) => url === '/api/editor/save')).toHaveLength(1);
  expect(fixture.fetcher.mock.calls.some(([url]) => /generate|snapshots|\/build$|\/evaluate$/.test(url))).toBe(false);
});

it('mounts advertised workflow readiness in the real App without replacing authoring state or dispatching work', async () => {
  const ready = {schema_version: 2, workflow: 'agentic_generation', checked_at: null, policy: null, ready: false,
    checks: [
      {id: 'api_contract', status: 'passed', code: 'api_contract_available', required: true},
      {id: 'runtime', status: 'not_checked', code: 'runtime_not_checked', required: true},
      {id: 'generation_model', status: 'not_checked', code: 'generation_not_configured', required: true},
      {id: 'graph', status: 'not_checked', code: 'graph_not_configured', required: true},
      {id: 'policy_protocol', status: 'not_required', code: 'not_required', required: false},
      {id: 'policy_model', status: 'not_required', code: 'not_required', required: false},
      {id: 'policy_transport', status: 'not_required', code: 'not_required', required: false},
      {id: 'gpu', status: 'not_checked', code: 'resource_unknown', required: true},
    ]};
  const fixture = setup('/workspaces/default?layout=v7', url => {
    if (url === '/api/editor') return wire({default_document_id: 'fixture', documents: [file], capabilities: {workflow_readiness: true}, limitations: []});
    if (url === '/api/editor/readiness?version=2&workflow=agentic_generation') return wire(ready);
    if (url === '/api/editor/readiness/check') return wire({...ready, checked_at: 123});
  });
  await screen.findByText('graph_not_configured');
  await waitFor(() => expect(text()).toBe(source)); edit();
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await screen.findByText(/Last explicit check:/);
  expect(text()).toBe(edited);
  expect(fixture.fetcher.mock.calls.filter(([url]) => url === '/api/editor/readiness/check')).toHaveLength(1);
  const checked = fixture.fetcher.mock.calls.find(([url]) => url === '/api/editor/readiness/check')!;
  expect(JSON.parse(String(checked[1]?.body))).toMatchObject({schema_version: 2, workflow: 'agentic_generation', check_provider: false, yaml_text: edited});
  expect(fixture.fetcher.mock.calls.some(([url, init]) => init?.method === 'POST' && /\/editor\/(save|generate|snapshots|build|evaluate)$/.test(url))).toBe(false);
});

it('renders a durable generation diagnostic in the real historical job inspector without replay', async () => {
  const job = {id: 'observed-generation', workspace_id: 'default', kind: 'generate', status: 'indeterminate', stage: 'indeterminate', inputs: {}, result: null, error: null, created_at: 0, updated_at: 0, created_by_session_id: session.session_id, diagnostic: {schema_version: 1, code: 'provider_request_rejected', stage: 'agent_initializing'}};
  const fixture = setup('/jobs/observed-generation?layout=v7', url => {
    if (url === '/api/workspaces/default') return wire({id: 'default', name: 'Workspace', jobs: [job], event_cursor: 1});
    if (url === '/api/jobs/observed-generation') return wire(job);
  });
  await screen.findByText('The provider rejected the request.');
  expect(screen.getByText(/does not prove that the provider performed no work/)).toBeVisible();
  expect(fixture.fetcher.mock.calls.some(([url, init]) => init?.method === 'POST' && /\/editor\/(generate|build|evaluate|snapshots)$/.test(url))).toBe(false);
});

it.each(['verified', 'origin', 'root', 'canonical', 'manifest', 'source', 'family', 'view', 'late-session', 'late-navigation-ABA', 'late-source-ABA', 'late-detail-refresh'])('production durable → numbered save → dirty-confirmed exact research Open: %s', async outcome => {
  const preferences = outcome === 'verified' ? persistentPreferenceFixture() : undefined;
  const reservationId = '4'.repeat(32), researchRevision = '5'.repeat(32), manifestDigest = '6'.repeat(64), researchView = '7'.repeat(32);
  const descriptor = `research-version:local:${reservationId}:${manifestDigest}`;
  const manual = {kind: 'editor_revision', editor_revision_id: revisionId, source_hash: hash(edited), canonical_hash: canonical};
  const full = {...manual, schema_version: 1, bundle_codec: 'arena-editor-bundle/v1', bundle_sha256: '8'.repeat(64), receipt_sha256: '9'.repeat(64)};
  let request: Record<string, unknown> | undefined;
  let releaseResearch!: (response: Response) => void;
  let researchResponse: unknown;
  const reservation = () => ({store_id: 'local', family: 'Example', reservation_id: reservationId, revision_id: researchRevision, version: 1, source: full, parent_revision_id: null, workflow_id: request?.idempotency_key ?? 'older'});
  const identity = () => {const {workflow_id: _, parent_revision_id: __, ...r} = reservation(); return {...r, manifest_digest: manifestDigest};};
  const commit = () => ({reservation: reservation(), manifest: {digest: manifestDigest, binding: reservation(), files: {'environment.yaml': {size: new TextEncoder().encode(edited).length, sha256: hash(edited)}}}, relative_directory: 'final/Example/v1', publication_intent_id: null});
  const fixture = setup('/workspaces/default?layout=v7', (url, init) => {
    if (url === '/api/editor') return wire({default_document_id: 'fixture', documents: [file], capabilities: {generation: false, snapshots: false, neo4j: false, research_versions: true, manual_research_save: true, research_version_open: true}, limitations: []});
    if (url === '/api/research/stores') return wire({stores: [{store_id: 'local', available: true}]});
    if (url === '/api/research/stores/local/versions' && init?.method === 'POST') {request = JSON.parse(String(init.body)); return wire(commit());}
    if (url.includes('/versions?')) return wire({versions: request ? [{...reservation(), state: 'COMMITTED', manifest_digest: manifestDigest, open_source: {kind: 'research_version', id: descriptor}}] : [], latest_version: request ? 1 : null, next_after_version: null});
    if (url === `/api/research/stores/local/versions/${reservationId}`) return wire(commit());
    if (url === `/api/editor/documents/${encodeURIComponent(descriptor)}`) {
      researchResponse = {document_id: outcome === 'view' ? 'not-a-view' : researchView, source: descriptor,
        source_origin: {kind: 'research_version', id: outcome === 'origin' ? descriptor + 'extra' : descriptor},
        research_identity: {...identity(), ...(outcome === 'manifest' ? {manifest_digest: '0'.repeat(64)} : {}), ...(outcome === 'family' ? {family: 'Other'} : {}), ...(outcome === 'source' ? {source: {...full, bundle_sha256: '0'.repeat(64)}} : {})},
        yaml_text: edited, source_hash: outcome === 'root' ? '0'.repeat(64) : hash(edited), validation: {...projection(edited), ...(outcome === 'canonical' ? {canonical_hash: '0'.repeat(64)} : {})}};
      return outcome.startsWith('late-') ? new Promise<Response>(resolve => {releaseResearch = resolve;}) : wire(researchResponse);
    }
  });
  await waitFor(() => expect(text()).toBe(source));
  fireEvent.click(screen.getByRole('button', {name: 'Open research versions'}));
  expect(screen.queryByLabelText('Research save source')).not.toBeInTheDocument();
  edit(); fireEvent.click(screen.getByRole('button', {name: 'Validate schema'}));
  await waitFor(() => expect(screen.getByRole('button', {name: 'Save durable revision'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button', {name: 'Save durable revision'}));
  fireEvent.change(await screen.findByLabelText('Research save source'), {target: {value: 'manual'}});
  await screen.findByRole('option', {name: 'local'});
  fireEvent.change(screen.getByLabelText('Research store'), {target: {value: 'local'}});
  fireEvent.change(screen.getByLabelText('Research family'), {target: {value: 'Example'}});
  fireEvent.change(screen.getByLabelText('Parent revision'), {target: {value: 'none'}});
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', {name: 'Save numbered research version'}));
  await screen.findByText('Research version saved and verified. Graph publication was not performed.');
  expect(request).toEqual({idempotency_key: expect.any(String), family: 'Example', parent_revision_id: null, source: manual});
  expect(fixture.fetcher.mock.calls.some(([u]) => u.includes(encodeURIComponent(descriptor)))).toBe(false);
  fireEvent.click(await screen.findByRole('button', {name: 'Select version 1'}));
  const open = await screen.findByRole('button', {name: 'Open research version in editor'});
  vi.mocked(window.confirm).mockReturnValue(false); fireEvent.click(open);
  expect(fixture.fetcher.mock.calls.some(([u]) => u.includes(encodeURIComponent(descriptor)))).toBe(false);
  vi.mocked(window.confirm).mockImplementationOnce(() => {void fixture.cache.invalidateQueries({queryKey: ['research-version']}); return true;});
  fireEvent.click(open);
  expect(fixture.fetcher.mock.calls.some(([u]) => u.includes(encodeURIComponent(descriptor)))).toBe(false);
  await waitFor(() => expect(screen.getByRole('button', {name: 'Open research version in editor'})).toBeEnabled());
  vi.mocked(window.confirm).mockReturnValue(true); fireEvent.click(screen.getByRole('button', {name: 'Open research version in editor'}));
  if (outcome.startsWith('late-')) {
    await waitFor(() => expect(releaseResearch).toBeTypeOf('function'));
    if (outcome === 'late-session') {fixture.api.session = {...fixture.api.session!}; fixture.redraw();}
    if (outcome === 'late-navigation-ABA') {fireEvent.click(screen.getByRole('link', {name: 'Library'})); fireEvent.click(screen.getByRole('link', {name: 'Environment editor'}));}
    if (outcome === 'late-source-ABA') {edit('env_name: changed\n'); edit(edited);}
    if (outcome === 'late-detail-refresh') await act(async () => {await fixture.cache.invalidateQueries({queryKey: ['research-version']});});
    await act(async () => releaseResearch(wire(researchResponse)));
    await waitFor(() => expect(screen.getByLabelText('Document')).toHaveValue('fixture'));
    expect(text()).toBe(edited);
    expect(recentIds()).not.toContain(descriptor);
    return;
  }
  if (outcome !== 'verified') {
    await screen.findByText('Source identity or hash verification failed. No replacement or recent open recorded.');
    expect(screen.getByLabelText('Document')).toHaveValue('fixture');
    expect(text()).toBe(edited);
    expect(recentIds()).not.toContain(descriptor);
    return;
  }
  await waitFor(() => expect(screen.getByLabelText('Document')).toHaveValue(descriptor));
  expect(text()).toBe(edited);
  edit(edited + '# research draft\n');
  fireEvent.click(screen.getByRole('button', {name: 'Validate schema'}));
  await waitFor(() => expect(fixture.fetcher.mock.calls.filter(([u]) => u.endsWith('/editor/validate')).at(-1)?.[1]?.body).toContain(researchView));
  await waitFor(() => expect(JSON.parse(sessionStorage.getItem('arena.editor.draft.v1')!).documentId).toBe(descriptor));
  expect(recentIds()).toContain(descriptor);
  fireEvent.click(screen.getByRole('link', {name: 'Library'}));
  fireEvent.click(within(screen.getByRole('region', {name: 'Recent opens'})).getByRole('button', {name: `Inspect reference ${descriptor}`}));
  expect(screen.getByRole('button', {name: 'Pin exact revision'})).toBeEnabled();
  fireEvent.click(screen.getByRole('button', {name: 'Pin exact revision'}));
  await waitFor(() => expect(within(screen.getByRole('region', {name: 'Pinned revisions'})).getByText(descriptor)).toBeVisible());
  expect(preferences!()?.pins).toEqual([expect.objectContaining({id: descriptor, research_identity: identity()})]);
  expect(localStorage.getItem('arena.environment-library.v1')).toBeNull();
  const reads = fixture.fetcher.mock.calls.filter(([u]) => u.includes(encodeURIComponent(descriptor))).length;
  vi.mocked(window.confirm).mockReturnValue(false);
  fireEvent.click(screen.getByRole('button', {name: 'Open source in editor'}));
  expect(fixture.fetcher.mock.calls.filter(([u]) => u.includes(encodeURIComponent(descriptor)))).toHaveLength(reads);
  vi.mocked(window.confirm).mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', {name: 'Open source in editor'}));
  await waitFor(() => expect(text()).toBe(edited));
  expect(fixture.fetcher.mock.calls.filter(([u]) => u.includes(encodeURIComponent(descriptor)))).toHaveLength(reads + 1);
  expect(fixture.fetcher.mock.calls.some(([u]) => /candidates|publication/.test(u))).toBe(false);
  // Reloaded preferences remain hints: no persistent verification inventory.
  fixture.unmount(); sessionStorage.clear();
  const reloaded = setup('/library', url => url === '/api/editor' ? wire({documents: [file], capabilities: {research_version_open: true}, limitations: []}) : undefined);
  await screen.findByRole('button', {name: 'Inspect Fixture file'});
  fireEvent.click(await within(screen.getByRole('region', {name: 'Pinned revisions'})).findByRole('button', {name: `Inspect reference ${descriptor}`}));
  expect(within(screen.getByRole('region', {name: 'Source inspection'})).getByText('Missing exact reference')).toBeVisible();
  expect(screen.getByRole('button', {name: 'Open source in editor'})).toBeDisabled();
  expect(reloaded.fetcher.mock.calls.some(([u, init]) => u.includes('/documents/') || init?.method === 'POST' && /versions|save|publication/.test(u))).toBe(false);
});

it('searches a valid research Library row through App without invoking nested metadata methods', async () => {
  const identity = {store_id: 'local', family: 'Example', version: 1, reservation_id: '4'.repeat(32), revision_id: '5'.repeat(32), manifest_digest: '6'.repeat(64), source: {kind: 'editor_revision', schema_version: 1, editor_revision_id: revisionId, source_hash: hash(edited), canonical_hash: canonical, bundle_codec: 'arena-editor-bundle/v1', bundle_sha256: '8'.repeat(64), receipt_sha256: '9'.repeat(64)}};
  const descriptor = `research-version:local:${identity.reservation_id}:${identity.manifest_digest}`;
  const row = {id: descriptor, name: 'Research fixture', source: descriptor, kind: 'research_version', revision_id: identity.revision_id, source_hash: hash(edited), canonical_hash: canonical, research_identity: identity};
  const fixture = setup('/library', url => url === '/api/editor' ? wire({documents: [row], capabilities: {research_version_open: true}, limitations: []}) : undefined);
  await screen.findByRole('button', {name: 'Inspect Research fixture'});
  fireEvent.change(screen.getByLabelText('Search library'), {target: {value: 'no-such-metadata'}});
  expect(screen.getByText('No matching sources.')).toBeVisible();
  fireEvent.change(screen.getByLabelText('Search library'), {target: {value: 'Research fixture'}});
  expect(screen.getByRole('button', {name: 'Inspect Research fixture'})).toBeVisible();
  expect(fixture.fetcher.mock.calls.some(([url]) => /documents\/|versions|publication/.test(url))).toBe(false);
});

it.each([false, undefined, true])('admits retained manual POST only from current index capability %s, independently of original source', async capability => {
  const manual = {kind: 'editor_revision', editor_revision_id: revisionId, source_hash: hash(edited), canonical_hash: canonical};
  const pending = {session: session.session_id, store: 'local', source: manual, body: {idempotency_key: 'retained-manual', family: 'Example', parent_revision_id: null, source: manual}};
  const raw = JSON.stringify(pending); sessionStorage.setItem('arena:research-version:pending:v1', raw);
  const fixture = setup('/workspaces/default', (url, init) => {
    if (url === '/api/editor') return wire({default_document_id: 'fixture', documents: [file], capabilities: {research_versions: true, ...(capability !== undefined ? {manual_research_save: capability} : {})}, limitations: []});
    if (url === '/api/research/stores') return wire({stores: [{store_id: 'local', available: true}]});
    if (url.includes('/versions?')) return wire({versions: [], latest_version: null, next_after_version: null});
    if (init?.method === 'POST' && url.endsWith('/versions')) return wire({detail: 'lost acknowledgment'}, 503);
  });
  await waitFor(() => expect(text()).toBe(source));
  fireEvent.click(screen.getByRole('button', {name: 'Open research versions'}));
  const retry = await screen.findByRole('button', {name: 'Retry exact research save'});
  expect(screen.queryByLabelText('Research save source')).not.toBeInTheDocument();
  expect(fixture.fetcher.mock.calls.filter(([u, i]) => u.endsWith('/versions') && i?.method === 'POST')).toHaveLength(0);
  if (capability === true) {
    expect(retry).toBeEnabled(); vi.spyOn(window, 'confirm').mockReturnValue(true); fireEvent.click(retry);
    await screen.findByText(/Save unresolved/);
    expect(fixture.fetcher.mock.calls.filter(([u, i]) => u.endsWith('/versions') && i?.method === 'POST').map(([, i]) => i!.body)).toEqual([JSON.stringify(pending.body)]);
  } else {
    expect(retry).toBeDisabled();
    const key = Object.keys(retry).find(k => k.startsWith('__reactProps$'))!;
    const retained = (retry as unknown as Record<string, {onClick: () => void}>)[key].onClick;
    vi.spyOn(window, 'confirm').mockReturnValue(true); act(retained);
    expect(fixture.fetcher.mock.calls.filter(([u, i]) => u.endsWith('/versions') && i?.method === 'POST')).toHaveLength(0);
  }
  expect(sessionStorage.getItem('arena:research-version:pending:v1')).toBe(raw);
  expect(fixture.fetcher.mock.calls.some(([u]) => /candidates|publication/.test(u))).toBe(false);
});

it.each(['before-click ABA', 'confirmation ABA', 'POST ABA', 'GET ABA', 'POST error ABA', 'GET error ABA', 'POST session', 'GET session', 'storage replaced', 'cancel'])('fences retained manual retry through actual App/ApiClient: %s', async boundary => {
  const manual = {kind: 'editor_revision', editor_revision_id: revisionId, source_hash: hash(edited), canonical_hash: canonical};
  const pending = {session: session.session_id, store: 'local', source: manual, body: {idempotency_key: 'retained-manual', family: 'Example', parent_revision_id: null, source: manual}};
  const full = {...manual, schema_version: 1, bundle_codec: 'arena-editor-bundle/v1', bundle_sha256: '8'.repeat(64), receipt_sha256: '9'.repeat(64)};
  const reservation = {store_id: 'local', family: 'Example', reservation_id: '4'.repeat(32), revision_id: '5'.repeat(32), version: 1, parent_revision_id: null, workflow_id: pending.body.idempotency_key, source: full};
  const commit = {reservation, manifest: {digest: '6'.repeat(64), binding: reservation, files: {'environment.yaml': {size: edited.length, sha256: hash(edited)}}}, relative_directory: 'final/Example/v1', publication_intent_id: null};
  const raw = JSON.stringify(pending); sessionStorage.setItem('arena:research-version:pending:v1', raw);
  let release!: (value: Response) => void;
  const fixture = setup('/workspaces/default', (url, init) => {
    if (url === '/api/editor') return wire({default_document_id: 'fixture', documents: [file], capabilities: {research_versions: true, manual_research_save: true}, limitations: []});
    if (url === '/api/research/stores') return wire({stores: [{store_id: 'local', available: true}]});
    if (url.includes('/versions?')) return wire({versions: [], latest_version: null, next_after_version: null});
    if (init?.method === 'POST' && url.endsWith('/versions')) return boundary.startsWith('POST') ? new Promise<Response>(resolve => {release = resolve;}) : wire(commit);
    if (url.endsWith(`/versions/${reservation.reservation_id}`)) return boundary.startsWith('GET') ? new Promise<Response>(resolve => {release = resolve;}) : wire(commit);
  });
  await waitFor(() => expect(text()).toBe(source));
  fireEvent.click(screen.getByRole('button', {name: 'Open research versions'}));
  const retry = screen.getByRole('button', {name: 'Retry exact research save'});
  expect(retry).toBeEnabled();
  const captured = (retry as unknown as Record<string, {onClick: () => void}>)[Object.keys(retry).find(k => k.startsWith('__reactProps$'))!].onClick;
  const query = fixture.cache.getQueryCache().find({queryKey: ['editor'], exact: false})!;
  const original = query.state.data as {capabilities: Record<string, boolean>};
  const aba = () => {
    fixture.cache.setQueryData(query.queryKey, {...original, capabilities: {...original.capabilities, manual_research_save: false}});
    fixture.cache.setQueryData(query.queryKey, original);
  };
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(boundary !== 'cancel');
  if (boundary === 'confirmation ABA') confirm.mockImplementationOnce(() => {aba(); return true;});
  const sibling = JSON.stringify({...pending, body: {...pending.body, idempotency_key: 'sibling-request'}});
  if (boundary === 'storage replaced') sessionStorage.setItem('arena:research-version:pending:v1', sibling);
  act(() => {if (boundary === 'before-click ABA') aba(); captured();});
  if (boundary.startsWith('POST') || boundary.startsWith('GET')) {
    await waitFor(() => expect(release).toBeTypeOf('function'));
    act(() => {if (boundary.endsWith('session')) fixture.api.session = {...fixture.api.session!}; else aba();});
    await act(async () => release(boundary.includes('error') ? wire({detail: 'retired failure'}, 503) : wire(commit)));
    expect(fixture.fetcher.mock.calls.filter(([u, i]) => u.endsWith('/versions') && i?.method === 'POST').map(([, i]) => i!.body)).toEqual([JSON.stringify(pending.body)]);
    if (boundary.startsWith('POST')) expect(fixture.fetcher.mock.calls.filter(([u]) => u.endsWith(`/versions/${reservation.reservation_id}`))).toHaveLength(0);
  } else {
    expect(fixture.fetcher.mock.calls.filter(([u, i]) => u.endsWith('/versions') && i?.method === 'POST')).toHaveLength(0);
  }
  expect(screen.queryByText(/Save unresolved\./)).not.toBeInTheDocument();
  expect(screen.queryByText('Research version saved and verified. Graph publication was not performed.')).not.toBeInTheDocument();
  expect(sessionStorage.getItem('arena:research-version:pending:v1')).toBe(boundary === 'storage replaced' ? sibling : raw);
});

it.each(['unavailable', 'capability false', 'capability absent', 'conflict', 'duplicate', 'before-click ABA', 'confirmation ABA', 'GET ABA', 'GET missing', 'GET hash', 'owner', 'storage failure'])('keeps verified research Library discovery subordinate to live authority: %s', async boundary => {
  const full = {kind: 'editor_revision', schema_version: 1, editor_revision_id: revisionId, source_hash: hash(edited), canonical_hash: canonical, bundle_codec: 'arena-editor-bundle/v1', bundle_sha256: '8'.repeat(64), receipt_sha256: '9'.repeat(64)};
  const reservation = {store_id: 'local', family: 'Example', reservation_id: '4'.repeat(32), revision_id: '5'.repeat(32), version: 1, parent_revision_id: null, workflow_id: 'older', source: full};
  const manifest = {digest: '6'.repeat(64), binding: reservation, files: {'environment.yaml': {size: edited.length, sha256: hash(edited)}}};
  const {parent_revision_id: _, workflow_id: __, ...identityFields} = reservation;
  const identity = {...identityFields, manifest_digest: manifest.digest};
  const descriptor = `research-version:local:${reservation.reservation_id}:${manifest.digest}`;
  const row = {id: descriptor, kind: 'research_version', name: 'Example v1', source: descriptor, revision_id: reservation.revision_id, research_identity: identity, source_hash: hash(edited), canonical_hash: canonical};
  const doc = {document_id: '7'.repeat(32), source: descriptor, source_origin: {kind: 'research_version', id: descriptor}, research_identity: identity, yaml_text: edited, source_hash: hash(edited), validation: projection(edited)};
  const index = {default_document_id: 'fixture', documents: [file], capabilities: {research_versions: true, research_version_open: true}, limitations: []};
  let reopened = false, release!: (response: Response) => void, unavailable = false;
  const fixture = setup('/workspaces/default', (url) => {
    if (url === '/api/editor') return unavailable ? wire({detail: 'Unavailable'}, 503) : wire(index);
    if (url === '/api/research/stores') return wire({stores: [{store_id: 'local', available: true}]});
    if (url.includes('/versions?')) return wire({versions: [{...reservation, state: 'COMMITTED', manifest_digest: manifest.digest, open_source: {kind: 'research_version', id: descriptor}}], latest_version: 1, next_after_version: null});
    if (url.endsWith(`/versions/${reservation.reservation_id}`)) return wire({reservation, manifest, relative_directory: 'final/Example/v1', publication_intent_id: null});
    if (url === `/api/editor/documents/${encodeURIComponent(descriptor)}`) {
      if (reopened && boundary === 'GET ABA') return new Promise<Response>(resolve => {release = resolve;});
      return reopened && boundary === 'GET missing' ? wire({detail: 'Exact research source unavailable'}, 404) : wire(reopened && boundary === 'GET hash' ? {...doc, source_hash: '0'.repeat(64)} : doc);
    }
  });
  await waitFor(() => expect(text()).toBe(source));
  fireEvent.click(screen.getByRole('button', {name: 'Open research versions'}));
  await screen.findByRole('option', {name: 'local'});
  fireEvent.change(screen.getByLabelText('Research store'), {target: {value: 'local'}});
  fireEvent.change(screen.getByLabelText('Research family'), {target: {value: 'Example'}});
  fireEvent.click(await screen.findByRole('button', {name: 'Select version 1'}));
  fireEvent.click(await screen.findByRole('button', {name: 'Open research version in editor'}));
  await waitFor(() => expect(text()).toBe(edited));
  edit(edited + '# keep dirty\n');
  fireEvent.click(screen.getByRole('link', {name: 'Library'}));
  fireEvent.click(within(screen.getByRole('region', {name: 'Recent opens'})).getByRole('button', {name: `Inspect reference ${descriptor}`}));
  expect(screen.getByRole('button', {name: 'Pin exact revision'})).toBeEnabled();
  const open = screen.getByRole('button', {name: 'Open source in editor'});
  const captured = (open as unknown as Record<string, {onClick: () => void}>)[Object.keys(open).find(k => k.startsWith('__reactProps$'))!].onClick;
  const query = fixture.cache.getQueryCache().find({queryKey: ['editor'], exact: false})!;
  const aba = () => {fixture.cache.setQueryData(query.queryKey, {...index, capabilities: {...index.capabilities, research_version_open: false}}); fixture.cache.setQueryData(query.queryKey, index);};
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
  reopened = true;
  if (boundary === 'storage failure') {
    const set = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key, value) {if (key === 'arena.environment-library.v1') throw new DOMException('quota', 'QuotaExceededError'); return set.call(this, key, value);});
    const draftBackup = sessionStorage.getItem('arena.editor.draft.v1');
    fireEvent.click(screen.getByRole('button', {name: 'Pin exact revision'}));
    expect(await screen.findByText('Library preferences unavailable; using memory for this mount.')).toBeVisible();
    expect(within(screen.getByRole('region', {name: 'Pinned revisions'})).getByText(descriptor)).toBeVisible();
    expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(draftBackup);
    fireEvent.click(open); await waitFor(() => expect(text()).toBe(edited));
  } else if (boundary.startsWith('GET')) {
    fireEvent.click(open);
    if (boundary === 'GET ABA') {
      await waitFor(() => expect(release).toBeTypeOf('function')); act(aba);
      await act(async () => release(wire(doc)));
      expect(screen.getByRole('heading', {name: 'Library'})).toBeVisible();
    } else expect(await within(screen.getByRole('region', {name: 'Environment library'}).parentElement!).findByText(boundary === 'GET hash' ? 'Source identity or hash verification failed. No replacement or recent open recorded.' : 'Exact research source unavailable')).toBeVisible();
    fireEvent.click(screen.getByRole('link', {name: 'Environment editor'}));
    expect(text()).toBe(edited + '# keep dirty\n');
  } else {
    if (boundary === 'unavailable') {unavailable = true; fireEvent.click(screen.getByRole('button', {name: 'Refresh library'})); await screen.findByText('Sources unavailable. No replacement or latest-source fallback.');}
    if (boundary.startsWith('capability')) await act(async () => {fixture.cache.setQueryData(query.queryKey, {...index, capabilities: {research_versions: true, ...(boundary === 'capability false' ? {research_version_open: false} : {})}});});
    if (boundary === 'conflict' || boundary === 'duplicate') await act(async () => {fixture.cache.setQueryData(query.queryKey, {...index, documents: boundary === 'conflict' ? [{...row, source_hash: '0'.repeat(64)}] : [row, row]});});
    if (boundary === 'owner') {fixture.api.session = {...fixture.api.session!}; fixture.redraw();}
    if (boundary === 'confirmation ABA') confirm.mockImplementationOnce(() => {aba(); return true;});
    act(() => {if (boundary === 'before-click ABA') aba(); captured();});
    expect(fixture.fetcher.mock.calls.filter(([u]) => u.includes(encodeURIComponent(descriptor)))).toHaveLength(1);
    if (['unavailable', 'capability false', 'capability absent', 'conflict', 'duplicate'].includes(boundary)) await waitFor(() => expect(screen.getByRole('button', {name: 'Open source in editor'})).toBeDisabled());
  }
  expect(fixture.fetcher.mock.calls.some(([u, init]) => init?.method === 'POST' && /versions|save|publication/.test(u))).toBe(false);
});

it.each(['original', 'Library'].flatMap(entry => ['refresh error', 'capability false', 'capability absent', 'before-click ABA', 'retained after ABA', 'confirmation ABA', 'GET ABA', 'GET error ABA', 'GET refresh error'].map(boundary => ({entry, boundary}))))('fences research Open with current editor-index permission through $entry: $boundary', async ({entry, boundary}) => {
  const full = {kind: 'editor_revision', schema_version: 1, editor_revision_id: revisionId, source_hash: hash(edited), canonical_hash: canonical, bundle_codec: 'arena-editor-bundle/v1', bundle_sha256: '8'.repeat(64), receipt_sha256: '9'.repeat(64)};
  const reservation = {store_id: 'local', family: 'Example', reservation_id: '4'.repeat(32), revision_id: '5'.repeat(32), version: 1, parent_revision_id: null, workflow_id: 'older', source: full};
  const manifest = {digest: '6'.repeat(64), binding: reservation, files: {'environment.yaml': {size: edited.length, sha256: hash(edited)}}};
  const {parent_revision_id: _, workflow_id: __, ...identityFields} = reservation;
  const identity = {...identityFields, manifest_digest: manifest.digest};
  const descriptor = `research-version:local:${reservation.reservation_id}:${manifest.digest}`;
  const doc = {document_id: '7'.repeat(32), source: descriptor, source_origin: {kind: 'research_version', id: descriptor}, research_identity: identity, yaml_text: edited, source_hash: hash(edited), validation: projection(edited)};
  // The independently verified research descriptor is deliberately NOT an index row.
  const index = {default_document_id: 'fixture', documents: [file], capabilities: {research_versions: true, research_version_open: true}, limitations: []};
  let unavailable = false, defer = false, release!: (response: Response) => void;
  const fixture = setup('/workspaces/default', url => {
    if (url === '/api/editor') return unavailable ? wire({detail: 'Index refresh failed'}, 503) : wire(index);
    if (url === '/api/research/stores') return wire({stores: [{store_id: 'local', available: true}]});
    if (url.includes('/versions?')) return wire({versions: [{...reservation, state: 'COMMITTED', manifest_digest: manifest.digest, open_source: {kind: 'research_version', id: descriptor}}], latest_version: 1, next_after_version: null});
    if (url.endsWith(`/versions/${reservation.reservation_id}`)) return wire({reservation, manifest, relative_directory: 'final/Example/v1', publication_intent_id: null});
    if (url === `/api/editor/documents/${encodeURIComponent(descriptor)}`) return defer ? new Promise<Response>(resolve => {release = resolve;}) : wire(doc);
  });
  await waitFor(() => expect(text()).toBe(source));
  fireEvent.click(screen.getByRole('button', {name: 'Open research versions'}));
  await screen.findByRole('option', {name: 'local'});
  fireEvent.change(screen.getByLabelText('Research store'), {target: {value: 'local'}});
  fireEvent.change(screen.getByLabelText('Research family'), {target: {value: 'Example'}});
  fireEvent.click(await screen.findByRole('button', {name: 'Select version 1'}));
  await screen.findByRole('button', {name: 'Open research version in editor'});
  if (entry === 'Library') {
    fireEvent.click(screen.getByRole('button', {name: 'Open research version in editor'}));
    await waitFor(() => expect(text()).toBe(edited));
    await waitFor(() => expect(recentIds()).toContain(descriptor));
  }
  const dirty = 'env_name: retain_this_draft\n';
  edit(dirty);
  if (entry === 'Library') {
    fireEvent.click(screen.getByRole('link', {name: 'Library'}));
    fireEvent.click(within(screen.getByRole('region', {name: 'Recent opens'})).getByRole('button', {name: `Inspect reference ${descriptor}`}));
  }
  const buttonName = entry === 'original' ? 'Open research version in editor' : 'Open source in editor';
  const button = screen.getByRole('button', {name: buttonName});
  expect(button).toBeEnabled();
  const captured = (button as unknown as Record<string, {onClick: () => void}>)[Object.keys(button).find(k => k.startsWith('__reactProps$'))!].onClick;
  const query = fixture.cache.getQueryCache().find({queryKey: ['editor'], exact: false});
  expect(query).toBeDefined();
  const aba = () => {
    fixture.cache.setQueryData(query!.queryKey, {...index, capabilities: {...index.capabilities, research_version_open: false}});
    fixture.cache.setQueryData(query!.queryKey, index);
  };
  const refreshError = async () => {
    unavailable = true;
    await act(async () => {await fixture.cache.refetchQueries({queryKey: query!.queryKey, exact: true});});
    expect(query!.state.status).toBe('error');
    expect((query!.state.data as typeof index).capabilities.research_version_open).toBe(true);
  };
  const reads = () => fixture.fetcher.mock.calls.filter(([u]) => u === `/api/editor/documents/${encodeURIComponent(descriptor)}`);
  const before = reads().length;
  const recents = localStorage.getItem('arena.environment-library.v1');
  const pending = sessionStorage.getItem('arena:research-version:pending:v1');
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
  if (boundary.startsWith('GET')) {
    defer = true; act(captured);
    await waitFor(() => expect(release).toBeTypeOf('function'));
    if (boundary === 'GET refresh error') await refreshError(); else act(aba);
    // A retired load must release its busy UI even before the old GET settles.
    expect(screen.queryByText('Opening exact source…')).not.toBeInTheDocument();
    await act(async () => {
      release(boundary === 'GET error ABA' ? wire({detail: 'Retired document failure'}, 503) : wire(doc));
      await new Promise(resolve => setTimeout(resolve, 30));
    });
    expect(reads()).toHaveLength(before + 1);
    expect(screen.queryByText('Retired document failure')).not.toBeInTheDocument();
  } else {
    if (boundary === 'refresh error') await refreshError();
    if (boundary.startsWith('capability')) await act(async () => {
      fixture.cache.setQueryData(query!.queryKey, {...index, capabilities: {research_versions: true, ...(boundary === 'capability false' ? {research_version_open: false} : {})}});
    });
    if (boundary === 'retained after ABA') {
      await act(async () => {aba(); await new Promise(resolve => setTimeout(resolve, 30));});
      await waitFor(() => {
        const freshButton = screen.getByRole('button', {name: buttonName});
        expect(freshButton).toBeEnabled();
        expect((freshButton as unknown as Record<string, {onClick: () => void}>)[Object.keys(freshButton).find(k => k.startsWith('__reactProps$'))!].onClick).not.toBe(captured);
      });
    }
    if (boundary === 'confirmation ABA') confirm.mockImplementationOnce(() => {aba(); return true;});
    act(() => {if (boundary === 'before-click ABA') aba(); captured();});
    expect(reads()).toHaveLength(before);
    if (boundary !== 'confirmation ABA') expect(confirm).not.toHaveBeenCalled();
    if (['refresh error', 'capability false', 'capability absent'].includes(boundary)) await waitFor(() => expect(screen.getByRole('button', {name: buttonName})).toBeDisabled());
  }
  expect(localStorage.getItem('arena.environment-library.v1')).toBe(recents);
  expect(sessionStorage.getItem('arena:research-version:pending:v1')).toBe(pending);
  if (entry === 'Library') fireEvent.click(screen.getByRole('link', {name: 'Environment editor'}));
  expect(text()).toBe(dirty);
  expect(screen.getByLabelText('Document')).toHaveValue(entry === 'original' ? 'fixture' : descriptor);
  // A new explicit control can use fresh admission; retired consent never revives.
  unavailable = false; defer = false;
  await act(async () => {await fixture.cache.refetchQueries({queryKey: query!.queryKey, exact: true});});
  if (entry === 'original') {
    fireEvent.click(screen.getByRole('link', {name: 'Library'}));
    expect(screen.queryByRole('button', {name: 'Inspect Example v1'})).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', {name: 'Environment editor'}));
    fireEvent.click(screen.getByRole('button', {name: 'Open research versions'}));
    await screen.findByRole('option', {name: 'local'});
    fireEvent.change(screen.getByLabelText('Research store'), {target: {value: 'local'}});
    fireEvent.change(screen.getByLabelText('Research family'), {target: {value: 'Example'}});
    fireEvent.click(await screen.findByRole('button', {name: 'Select version 1'}));
  } else {
    fireEvent.click(screen.getByRole('link', {name: 'Library'}));
  }
  await waitFor(() => expect(screen.getByRole('button', {name: buttonName})).toBeEnabled());
  const freshReads = reads().length;
  fireEvent.click(screen.getByRole('button', {name: buttonName}));
  await waitFor(() => expect(text()).toBe(edited));
  expect(reads()).toHaveLength(freshReads + 1);
  expect(fixture.fetcher.mock.calls.some(([u, init]) => init?.method === 'POST' && /versions|save|publication|generate|snapshots/.test(u))).toBe(false);
});

it('retires the verified manual save offer on explicit same-source replacement, even when view bytes and ID repeat', async () => {
  setup('/workspaces/default', url => {
    if (url === '/api/editor') return wire({default_document_id: 'fixture', documents: [file], capabilities: {research_versions: true, manual_research_save: true, research_version_open: true}, limitations: []});
    if (url === '/api/research/stores') return wire({stores: []});
  });
  await waitFor(() => expect(screen.getByRole('button', {name: 'Save durable revision'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button', {name: 'Save durable revision'}));
  await screen.findByRole('button', {name: 'Open saved revision'});
  fireEvent.click(screen.getByRole('button', {name: 'Open research versions'}));
  expect(screen.getByLabelText('Research save source')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Document'), {target: {value: 'fixture'}});
  await waitFor(() => expect(screen.getByLabelText('Document')).toBeEnabled());
  expect(screen.queryByLabelText('Research save source')).not.toBeInTheDocument();
});
it.each(['manual', 'candidate'])('restores a research draft only after exact %s identity verification despite a fresh view UUID and absent mutable index', async kind => {
  const researchIdentity = {store_id: 'local', reservation_id: '4'.repeat(32), revision_id: '5'.repeat(32), family: 'Example', version: 2, manifest_digest: '6'.repeat(64), source: kind === 'manual'
    ? {kind: 'editor_revision', schema_version: 1, editor_revision_id: revisionId, source_hash: hash(source), canonical_hash: canonical, bundle_codec: 'arena-editor-bundle/v1', bundle_sha256: '8'.repeat(64), receipt_sha256: '9'.repeat(64)}
    : {job_id: 'a'.repeat(32), attempt_id: 'b'.repeat(32), generation: 1, receipt_sha256: 'c'.repeat(64), request_sha256: 'd'.repeat(64)}};
  const descriptor = `research-version:local:${researchIdentity.reservation_id}:${researchIdentity.manifest_digest}`;
  const backup = {version: 1, documentId: descriptor, viewId, sourceHash: hash(source), draft: edited, prompt: 'retain research draft', researchIdentity};
  sessionStorage.setItem('arena.editor.draft.v1', JSON.stringify(backup));
  const fixture = setup('/workspaces/default', url => url === `/api/editor/documents/${encodeURIComponent(descriptor)}` ? wire({document_id: reopenedView, source: descriptor, source_origin: {kind: 'research_version', id: descriptor}, research_identity: researchIdentity, yaml_text: source, source_hash: hash(source), validation: projection(source)}) : undefined);
  await waitFor(() => expect(screen.getByRole('button', {name: 'Restore draft'})).toBeEnabled());
  expect(text()).toBe(source);
  fireEvent.click(screen.getByRole('link', {name: 'Library'}));
  fireEvent.click(screen.getByRole('link', {name: 'Environment editor'}));
  expect(screen.getByRole('button', {name: 'Restore draft'})).toBeEnabled();
  fireEvent.click(screen.getByRole('button', {name: 'Restore draft'}));
  await waitFor(() => expect(text()).toBe(edited));
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('retain research draft');
  expect(fixture.fetcher.mock.calls.filter(([u]) => u.includes('/editor/documents/')).map(([u]) => u)).toEqual([`/api/editor/documents/${encodeURIComponent(descriptor)}`]);
  expect(fixture.fetcher.mock.calls.some(([u, init]) => init?.method === 'POST' && /save|versions|publications/.test(u))).toBe(false);
});

it.each(['legacy', 'v7'])('uses the production Library → exact file → edited durable receipt → refreshed index → explicit immutable reopen path (%s)', async layout => {
  const {fetcher, history} = setup(`/library?layout=${layout}`);
  await screen.findByRole('heading', {name: 'Library'});
  expect(fetcher.mock.calls.some(([url]) => /documents|model-settings|previews/.test(url))).toBe(false);
  await openFile();
  expect(history.location.pathname).toBe('/workspaces/default');
  await waitFor(() => expect(recentIds()).toEqual(['fixture']));
  edit();
  fireEvent.click(screen.getByRole('button', {name: 'Validate schema'}));
  await waitFor(() => expect(screen.getByRole('button', {name: 'Save durable revision'})).toBeEnabled());
  const reads = fetcher.mock.calls.filter(([url]) => url === '/api/editor').length;
  fireEvent.click(screen.getByRole('button', {name: 'Save durable revision'}));
  await screen.findByRole('button', {name: 'Open saved revision'});
  const saves = fetcher.mock.calls.filter(([url]) => url === '/api/editor/save');
  expect(saves).toHaveLength(1);
  const request = JSON.parse(saves[0][1]!.body as string);
  expect(request).toMatchObject({yaml_text: edited, document_id: viewId, expected_source_hash: hash(source), idempotency_key: expect.any(String)});
  expect(fetcher.mock.calls.some(([url]) => url === `/api/editor/save-requests/${request.idempotency_key}`)).toBe(true);
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url === '/api/editor').length).toBeGreaterThan(reads));
  expect(fetcher.mock.calls.some(([url]) => url.includes(encodeURIComponent(revisionSource)))).toBe(false);
  expect(screen.getByLabelText('Document')).toHaveValue('fixture');
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', {name: 'Open saved revision'}));
  await waitFor(() => expect(screen.getByLabelText('Document')).toHaveValue(revisionSource));
  expect(fetcher.mock.calls.some(([url]) => url === `/api/editor/documents/${encodeURIComponent(revisionSource)}`)).toBe(true);
  expect(text()).toBe(edited);
  await waitFor(() => expect(recentIds()).toEqual([revisionSource, 'fixture']));
  fireEvent.click(screen.getByRole('link', {name: 'Library'}));
  fireEvent.click(await screen.findByRole('button', {name: 'Inspect Saved fixture'}));
  expect(within(screen.getByRole('region', {name: 'Source inspection'})).getByRole('button', {name: 'Pin exact revision'})).toBeEnabled();
  expect(fetcher.mock.calls.some(([url, init]) => init?.method === 'POST' && /generate|snapshots|versions|publications/.test(url))).toBe(false);
});

it.each(['navigation ABA', 'catalogue unavailable'])('retires a captured Library Open handler after %s', async retirement => {
  let unavailable = false;
  const {fetcher} = setup('/library', url => unavailable && url === '/api/editor' ? wire({detail: 'offline'}, 503) : undefined);
  fireEvent.click(await screen.findByRole('button', {name: 'Inspect Fixture file'}));
  const button = screen.getByRole('button', {name: 'Open source in editor'});
  const key = Object.keys(button).find(key => key.startsWith('__reactProps$'))!;
  const captured = (button as unknown as Record<string, {onClick: () => void}>)[key].onClick;
  if (retirement === 'navigation ABA') {
    fireEvent.click(screen.getByRole('link', {name: 'Jobs & diagnostics'}));
    await screen.findByLabelText('Filter jobs');
    fireEvent.click(screen.getByRole('link', {name: 'Library'}));
    await screen.findByRole('heading', {name: 'Library'});
  } else {
    unavailable = true; fireEvent.click(screen.getByRole('button', {name: 'Refresh library'}));
    await screen.findByText('Sources unavailable. No replacement or latest-source fallback.');
  }
  const before = fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/')).length;
  act(() => captured());
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 30)); });
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(before);
  expect(recentIds()).toEqual([]);
});

it('retires in-flight Open UI across navigation and ignores the late response without recording a recent', async () => {
  let release!: (response: Response) => void;
  setup('/library', url => url.endsWith('/editor/documents/fixture') ? new Promise<Response>(resolve => {release = resolve;}) : undefined);
  fireEvent.click(await screen.findByRole('button', {name: 'Inspect Fixture file'}));
  fireEvent.click(screen.getByRole('button', {name: 'Open source in editor'}));
  await screen.findByText('Opening exact source…');
  fireEvent.click(screen.getByRole('link', {name: 'Jobs & diagnostics'}));
  await screen.findByLabelText('Filter jobs');
  fireEvent.click(screen.getByRole('link', {name: 'Library'}));
  await screen.findByRole('heading', {name: 'Library'});
  expect(screen.queryByText('Opening exact source…')).not.toBeInTheDocument();
  await act(async () => release(wire({document_id: viewId, source: file.source, source_origin: {kind: file.kind, id: file.id}, yaml_text: source, source_hash: hash(source), validation: projection(source)})));
  expect(recentIds()).toEqual([]);
  expect(screen.getByRole('heading', {name: 'Library'})).toBeVisible();
});

it.each(['same row', 'unavailable', 'removed', 'root hash changed', 'canonical hash changed', 'hash ABA'])('retires a deferred catalogue Open on refresh: %s', async retirement => {
  let release!: (response: Response) => void;
  let refresh = false, restored = false;
  const fixture = setup('/library', url => {
    if (url.endsWith('/editor/documents/fixture')) return new Promise<Response>(resolve => {release = resolve;});
    if (url === '/api/editor' && refresh) {
      if (retirement === 'unavailable') return wire({detail: 'Unavailable'}, 503);
      const row = restored ? file : retirement === 'root hash changed' || retirement === 'hash ABA'
        ? {...file, source_hash: hash(edited)} : retirement === 'canonical hash changed' ? {...file, canonical_hash: 'b'.repeat(64)} : file;
      return wire({default_document_id: 'fixture', documents: retirement === 'removed' ? [] : [row], capabilities: {}, limitations: []});
    }
  });
  fireEvent.click(await screen.findByRole('button', {name: 'Inspect Fixture file'}));
  fireEvent.click(screen.getByRole('button', {name: 'Open source in editor'}));
  await waitFor(() => expect(release).toBeTypeOf('function'));
  refresh = true;
  fireEvent.click(screen.getByRole('button', {name: 'Refresh library'}));
  await waitFor(() => expect(screen.getByRole('button', {name: 'Refresh library'})).toBeEnabled());
  if (retirement === 'hash ABA') {
    restored = true;
    fireEvent.click(screen.getByRole('button', {name: 'Refresh library'}));
    await waitFor(() => expect(screen.getByRole('button', {name: 'Refresh library'})).toBeEnabled());
  }
  expect(screen.queryByText('Opening exact source…')).not.toBeInTheDocument();
  await act(async () => {
    release(wire({document_id: viewId, source: file.source, source_origin: {kind: file.kind, id: file.id}, yaml_text: source, source_hash: hash(source), validation: projection(source)}));
    await new Promise(resolve => setTimeout(resolve, 30));
  });
  expect(recentIds()).toEqual([]);
  expect(fixture.history.location.pathname).toBe('/library');
});

it('does not restore recovery into another selection source with coincident frozen view/hash', async () => {
  const recovery = {version: 1, documentId: 'fixture', viewId, sourceHash: hash(source), draft: edited, prompt: 'retain me'};
  sessionStorage.setItem('arena.editor.draft.v1', JSON.stringify(recovery));
  setup('/workspaces/default', url => {
    if (url === '/api/editor') return wire({default_document_id: 'fixture', documents: [file, {...file, id: 'other', name: 'Other file'}], capabilities: {}, limitations: []});
    if (url.endsWith('/editor/documents/other')) return wire({document_id: viewId, source: file.source, source_origin: {kind: 'discovered_file', id: 'other'}, yaml_text: source, source_hash: hash(source), validation: projection(source)});
  });
  await waitFor(() => expect(screen.getByRole('button', {name: 'Restore draft'})).toBeEnabled());
  fireEvent.click(screen.getByRole('link', {name: 'Library'}));
  fireEvent.click(await screen.findByRole('button', {name: 'Inspect Other file'}));
  fireEvent.click(screen.getByRole('button', {name: 'Open source in editor'}));
  await waitFor(() => expect(screen.getByLabelText('Document')).toHaveValue('other'));
  expect(screen.getByRole('button', {name: 'Restore draft'})).toBeDisabled();
  expect(screen.getByRole('button', {name: 'Download recovered YAML'})).toBeEnabled();
  expect(JSON.parse(sessionStorage.getItem('arena.editor.draft.v1')!)).toEqual(recovery);
});

it('keeps the recovered immutable draft downloadable when its exact source is unavailable', async () => {
  const backup = {version: 1, documentId: revisionSource, viewId: reopenedView, sourceHash: hash(edited), draft: edited + '# unsaved', prompt: 'keep'};
  sessionStorage.setItem('arena.editor.draft.v1', JSON.stringify(backup));
  const {fetcher} = setup('/workspaces/default', url => url.includes('/editor/documents/') ? wire({detail: 'Exact revision unavailable'}, 404) : undefined);
  const download = await screen.findByRole('button', {name: 'Download recovered YAML'});
  expect(download).toBeEnabled();
  expect(screen.getByRole('button', {name: 'Restore draft'})).toBeDisabled();
  expect(JSON.parse(sessionStorage.getItem('arena.editor.draft.v1')!)).toEqual(backup);
  expect(fetcher.mock.calls.some(([url]) => url === '/api/editor/documents/fixture')).toBe(false);
});

it('cancels a dirty Library Open without document I/O, replacement or a new recent', async () => {
  const {fetcher} = setup('/workspaces/default');
  await waitFor(() => expect(text()).toBe(source)); edit();
  fireEvent.click(screen.getByRole('link', {name: 'Library'}));
  fireEvent.click(await screen.findByRole('button', {name: 'Inspect Fixture file'}));
  vi.spyOn(window, 'confirm').mockReturnValue(false);
  const count = fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/')).length;
  fireEvent.click(screen.getByRole('button', {name: 'Open source in editor'}));
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(count);
  expect(recentIds()).toEqual([]);
  fireEvent.click(screen.getByRole('link', {name: 'Environment editor'}));
  await waitFor(() => expect(text()).toBe(edited));
});

it.each(['conflict', 'bad receipt hash'])('retains the frozen save and withholds Open/index refresh after %s', async failure => {
  const {fetcher} = setup('/workspaces/default', (url, init) => {
    if (url === '/api/editor/save') return failure === 'conflict' ? wire({detail: 'Source changed'}, 409) : makeReceipt(JSON.parse(init!.body as string)).then(receipt => wire({...receipt, revision: {...receipt.revision, source_hash: '0'.repeat(64)}}));
  });
  await waitFor(() => expect(screen.getByRole('button', {name: 'Save durable revision'})).toBeEnabled());
  const before = fetcher.mock.calls.filter(([url]) => url === '/api/editor').length;
  fireEvent.click(screen.getByRole('button', {name: 'Save durable revision'}));
  await screen.findByText(/Conflict — invalid or replaced evidence/);
  expect(screen.queryByRole('button', {name: 'Open saved revision'})).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => url === '/api/editor')).toHaveLength(before);
  expect(sessionStorage.getItem('arena:editor-save:v1')).not.toBeNull();
  expect(screen.getByRole('button', {name: 'Retry exact save'})).toBeDisabled();
  expect(text()).toBe(source);
});

it.each(['session', 'client', 'navigation'])('withholds a late durable save acknowledgment after %s retirement', async retirement => {
  let release!: (response: Response) => void;
  let request!: EditorSaveRequest;
  const fixture = setup('/workspaces/default', (url, init) => url === '/api/editor/save' ? new Promise<Response>(resolve => {request = JSON.parse(init!.body as string); release = resolve;}) : undefined);
  await waitFor(() => expect(screen.getByRole('button', {name: 'Save durable revision'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button', {name: 'Save durable revision'}));
  await waitFor(() => expect(release).toBeTypeOf('function'));
  if (retirement === 'session') fixture.api.session = {...fixture.api.session!};
  else if (retirement === 'client') {fixture.redraw(new ApiClient(fixture.fetcher as typeof fetch)); await screen.findByRole('button', {name: 'Save durable revision'});}
  else {fireEvent.click(screen.getByRole('link', {name: 'Library'})); await screen.findByRole('heading', {name: 'Library'});}
  const before = fixture.fetcher.mock.calls.filter(([url]) => url === '/api/editor').length;
  await act(async () => release(wire(await makeReceipt(request))));
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.startsWith('/api/editor/save-requests/'))).toHaveLength(0);
  expect(fixture.fetcher.mock.calls.filter(([url]) => url === '/api/editor')).toHaveLength(before);
  expect(sessionStorage.getItem('arena:editor-save:v1')).not.toBeNull();
  expect(screen.queryByRole('button', {name: 'Open saved revision'})).not.toBeInTheDocument();
});

it.each(['root hash', 'origin', 'revision canonical'])('refuses explicit immutable Open with mismatched %s and preserves the draft', async failure => {
  const {fetcher} = setup('/workspaces/default', url => {
    if (url === '/api/editor') return wire({default_document_id: 'fixture', documents: [file, revisionRow], capabilities: {}, limitations: []});
    if (url === `/api/editor/documents/${encodeURIComponent(revisionSource)}`) return wire({document_id: reopenedView, source: revisionSource,
      source_origin: {kind: 'editor_revision', id: failure === 'origin' ? `editor-revision:${'4'.repeat(32)}` : revisionSource}, yaml_text: edited,
      source_hash: failure === 'root hash' ? '0'.repeat(64) : hash(edited), validation: {...projection(edited), canonical_hash: failure === 'revision canonical' ? 'b'.repeat(64) : canonical}});
  });
  await waitFor(() => expect(text()).toBe(source));
  fireEvent.click(screen.getByRole('link', {name: 'Library'}));
  fireEvent.click(await screen.findByRole('button', {name: 'Inspect Saved fixture'}));
  fireEvent.click(screen.getByRole('button', {name: 'Open source in editor'}));
  await waitFor(() => expect(screen.getByRole('region', {name: 'Environment library'}).parentElement).toHaveTextContent('Source identity or hash verification failed'));
  expect(recentIds()).toEqual([]);
  fireEvent.click(screen.getByRole('link', {name: 'Environment editor'}));
  await waitFor(() => expect(text()).toBe(source));
  expect(fetcher.mock.calls.filter(([url]) => url === '/api/editor/documents/fixture')).toHaveLength(1);
});

it('recovers a frozen save with GET only after source binding changes; does not open the accepted revision automatically', async () => {
  const request = {idempotency_key: 'prior-save', yaml_text: edited, document_id: reopenedView, expected_source_hash: hash(edited)};
  sessionStorage.setItem('arena:editor-save:v1', JSON.stringify({schema_version: 1, binding: 'old-source-binding', request, request_sha256: await editorSaveRequestHash(request)}));
  const {fetcher} = setup('/workspaces/default', url => url === '/api/editor/save-requests/prior-save' ? makeReceipt(request).then(wire) : undefined);
  // Read admission no longer implies that the initial source binding has settled.
  await waitFor(() => expect(text()).toBe(source));
  await waitFor(() => expect(screen.getByRole('button', {name: 'Check save status'})).toBeEnabled());
  expect(screen.getByRole('button', {name: 'Retry exact save'})).toBeDisabled();
  expect(fetcher.mock.calls.some(([url]) => url.includes('/save-requests/'))).toBe(false);
  fireEvent.click(screen.getByRole('button', {name: 'Check save status'}));
  await screen.findByRole('button', {name: 'Open saved revision'});
  expect(fetcher.mock.calls.some(([url]) => url === '/api/editor/save')).toBe(false);
  expect(screen.getByLabelText('Document')).toHaveValue('fixture');
  expect(text()).toBe(source);
  expect(sessionStorage.getItem('arena:editor-save:v1')).toBeNull();
});

it.each(['missing source', 'invalid source', 'pending draft recovery'])('checks a retained save independently of %s without POST or discarded recovery YAML', async state => {
  const request = {idempotency_key: 'prior-save', yaml_text: edited, document_id: reopenedView, expected_source_hash: hash(edited)};
  const retained = JSON.stringify({schema_version: 1, binding: 'old-source-binding', request, request_sha256: await editorSaveRequestHash(request)});
  const backup = JSON.stringify({version: 1, documentId: 'fixture', viewId, sourceHash: hash(source), draft: edited + '# must survive', prompt: 'keep this'});
  sessionStorage.setItem('arena:editor-save:v1', retained);
  sessionStorage.setItem('arena.editor.draft.v1', backup);
  const fixture = setup('/workspaces/default', url => {
    if (url === '/api/editor/documents/fixture' && state === 'missing source') return wire({detail: 'Source missing'}, 404);
    if (url === '/api/editor/documents/fixture' && state === 'invalid source') return wire({document_id: viewId, source: file.source, source_origin: {kind: file.kind, id: file.id}, yaml_text: source, source_hash: hash(source), validation: {...projection(source), valid: false}});
    if (url === '/api/editor/save-requests/prior-save') return makeReceipt(request).then(wire);
  });
  await waitFor(() => expect(fixture.fetcher.mock.calls.some(([url]) => url === '/api/editor/documents/fixture')).toBe(true));
  await waitFor(() => expect(screen.getByRole('button', {name: 'Check save status'})).toBeEnabled());
  expect(screen.getByRole('button', {name: 'Retry exact save'})).toBeDisabled();
  expect(fixture.fetcher.mock.calls.some(([url]) => url.includes('/save-requests/'))).toBe(false);
  expect(sessionStorage.getItem('arena:editor-save:v1')).toBe(retained);
  fireEvent.click(screen.getByRole('button', {name: 'Check save status'}));
  await screen.findByRole('button', {name: 'Open saved revision'});
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.includes('/save-requests/'))).toHaveLength(1);
  expect(fixture.fetcher.mock.calls.some(([url]) => url === '/api/editor/save')).toBe(false);
  expect(sessionStorage.getItem('arena:editor-save:v1')).toBeNull();
  expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(backup);
  expect(screen.getByRole('button', {name: 'Download recovered YAML'})).toBeEnabled();
  expect(text()).toBe(state === 'missing source' ? '' : source);
  expect(screen.getByRole('button', {name: 'Open saved revision'})).toBeEnabled();
  expect(recentIds()).toEqual([]);
});

it('denies retained save-status handlers while Library alone is active and after navigation ABA', async () => {
  const request = {idempotency_key: 'prior-save', yaml_text: edited, document_id: reopenedView, expected_source_hash: hash(edited)};
  const retained = JSON.stringify({schema_version: 1, binding: 'old-source-binding', request, request_sha256: await editorSaveRequestHash(request)});
  sessionStorage.setItem('arena:editor-save:v1', retained);
  const fixture = setup('/workspaces/default', url => url === '/api/editor/save-requests/prior-save' ? makeReceipt(request).then(wire) : undefined);
  await waitFor(() => expect(text()).toBe(source));
  const button = screen.getByRole('button', {name: 'Check save status'});
  const key = Object.keys(button).find(key => key.startsWith('__reactProps$'))!;
  const captured = (button as unknown as Record<string, {onClick: () => void}>)[key].onClick;
  fireEvent.click(screen.getByRole('link', {name: 'Library'}));
  await screen.findByRole('heading', {name: 'Library'});
  expect(button).toBeDisabled(); act(captured);
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
  fireEvent.click(screen.getByRole('link', {name: 'Environment editor'}));
  await waitFor(() => expect(screen.getByRole('button', {name: 'Check save status'})).toBeEnabled());
  act(captured);
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(fixture.fetcher.mock.calls.some(([url]) => /editor\/save/.test(url))).toBe(false);
  expect(sessionStorage.getItem('arena:editor-save:v1')).toBe(retained);
  fireEvent.click(screen.getByRole('button', {name: 'Check save status'}));
  await screen.findByRole('button', {name: 'Open saved revision'});
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.includes('/save-requests/'))).toHaveLength(1);
});

it.each(['verified', 'wrong hash'])('requires explicit confirmed exact receipt Open with an invalid draft and unavailable catalogue: %s', async outcome => {
  const request = {idempotency_key: 'prior-save', yaml_text: edited, document_id: reopenedView, expected_source_hash: hash(edited)};
  sessionStorage.setItem('arena:editor-save:v1', JSON.stringify({schema_version: 1, binding: 'old-source-binding', request, request_sha256: await editorSaveRequestHash(request)}));
  let unavailable = false;
  const fixture = setup('/workspaces/default', url => {
    if (url === '/api/editor' && unavailable) return wire({detail: 'offline'}, 503);
    if (url === '/api/editor/validate') return wire({...projection('invalid: ['), valid: false, summary: 'Invalid current draft'});
    if (url === '/api/editor/save-requests/prior-save') {unavailable = true; return makeReceipt(request).then(wire);}
    if (outcome === 'wrong hash' && url === `/api/editor/documents/${encodeURIComponent(revisionSource)}`) return wire({document_id: reopenedView, source: revisionSource, source_origin: {kind: 'editor_revision', id: revisionSource}, yaml_text: edited, source_hash: '0'.repeat(64), validation: projection(edited)});
  });
  await waitFor(() => expect(text()).toBe(source)); edit('invalid: [');
  fireEvent.click(screen.getByRole('button', {name: 'Validate schema'}));
  await screen.findByText('Invalid current draft');
  fireEvent.click(screen.getByRole('button', {name: 'Check save status'}));
  const open = await screen.findByRole('button', {name: 'Open saved revision'});
  expect(open).toBeEnabled(); expect(recentIds()).toEqual([]);
  expect(text()).toBe('invalid: [');
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  fireEvent.click(open); expect(confirm).toHaveBeenCalledOnce();
  expect(fixture.fetcher.mock.calls.some(([url]) => url.includes(encodeURIComponent(revisionSource)))).toBe(false);
  expect(text()).toBe('invalid: ['); expect(recentIds()).toEqual([]);
  confirm.mockReturnValue(true); fireEvent.click(open);
  if (outcome === 'verified') {
    await waitFor(() => expect(text()).toBe(edited));
    await waitFor(() => expect(recentIds()).toEqual([revisionSource]));
  } else {
    await screen.findByText('Source identity or hash verification failed. No replacement or recent open recorded.');
    expect(text()).toBe('invalid: ['); expect(recentIds()).toEqual([]);
  }
  expect(fixture.fetcher.mock.calls.some(([url]) => url === '/api/editor/save')).toBe(false);
});

it.each(['verified', 'unavailable', 'origin', 'root'])('restores immutable-source backup through its issued view without descriptor reissue or replay: %s', async outcome => {
  let descriptorOpens = 0;
  let reloading = false;
  const issued = new Map<string, object>();
  const transport = (url: string) => {
    if (url === '/api/editor') return wire({default_document_id: 'fixture', documents: [file, revisionRow], capabilities: {}, limitations: []});
    if (url === `/api/editor/documents/${encodeURIComponent(revisionSource)}`) {
      // The real backend issues a fresh UUID on every descriptor open.
      const id = (++descriptorOpens === 1 ? '3' : '4').repeat(32);
      const doc = {document_id: id, source: revisionSource, source_origin: {kind: 'editor_revision', id: revisionSource}, yaml_text: edited, source_hash: hash(edited), validation: projection(edited)};
      issued.set(id, doc);
      return wire(doc);
    }

    const doc = issued.get(url.slice('/api/editor/documents/'.length));
    if (url.startsWith('/api/editor/documents/') && doc) {
      if (reloading && outcome === 'unavailable') return wire({detail: 'Issued view unavailable'}, 404);
      return wire({...doc, ...(reloading && outcome === 'origin' ? {source_origin: {kind: 'editor_revision', id: 'editor-revision:' + 'f'.repeat(32)}} : {}), ...(reloading && outcome === 'root' ? {source_hash: '0'.repeat(64)} : {})});
    }
  };
  const first = setup('/workspaces/default', transport);
  await waitFor(() => expect(text()).toBe(source));
  fireEvent.change(screen.getByRole('combobox', {name: 'Document'}), {target: {value: revisionSource}});
  await waitFor(() => expect(text()).toBe(edited));
  edit(edited + '# retained');
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), {target: {value: 'review later'}});
  const retained = sessionStorage.getItem('arena.editor.draft.v1')!;
  const backup = JSON.parse(retained);
  expect(backup).toMatchObject({documentId: revisionSource, viewId: reopenedView, sourceHash: hash(edited), draft: edited + '# retained', prompt: 'review later'});
  first.unmount(); first.cache.clear(); reloading = true;
  const {fetcher} = setup('/workspaces/default', transport);
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url === `/api/editor/documents/${reopenedView}`)).toBe(true));
  expect(descriptorOpens).toBe(1);
  if (outcome !== 'verified') {
    await screen.findByText(outcome === 'unavailable' ? 'Issued view unavailable' : 'Source identity or hash verification failed. No replacement or recent open recorded.');
    expect(screen.getByRole('button', {name: 'Restore draft'})).toBeDisabled();
    expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(retained);
    expect(fetcher.mock.calls.some(([url, init]) => init?.method === 'POST' && /save|generate|snapshots|build|evaluate|publications/.test(url))).toBe(false);
    return;
  }
  await waitFor(() => expect(screen.getByRole('button', {name: 'Restore draft'})).toBeEnabled());
  expect(text()).toBe(edited);
  fireEvent.click(screen.getByRole('button', {name: 'Restore draft'}));
  expect(text()).toBe(backup.draft);
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue(backup.prompt);
  expect(JSON.parse(sessionStorage.getItem('arena.editor.draft.v1')!)).toMatchObject({documentId: revisionSource, viewId: reopenedView, sourceHash: hash(edited)});
  fireEvent.click(screen.getByRole('button', {name: 'Validate schema'}));
  await waitFor(() => expect(fetcher.mock.calls.some(([url, init]) => url === '/api/editor/validate' && JSON.parse(init!.body as string).document_id === reopenedView)).toBe(true));
  expect(fetcher.mock.calls.some(([url, init]) => init?.method === 'POST' && /save|generate|snapshots|build|evaluate|publications/.test(url))).toBe(false);
});

it('withholds catalogue actions throughout refresh and unavailable state without changing retained inspection', async () => {
  let release!: (response: Response) => void; let refresh = false;
  setup('/library', url => refresh && url === '/api/editor' ? new Promise<Response>(resolve => {release = resolve;}) : undefined);
  fireEvent.click(await screen.findByRole('button', {name: 'Inspect Fixture file'}));
  refresh = true; fireEvent.click(screen.getByRole('button', {name: 'Refresh library'}));
  await screen.findByText('Loading sources…');
  expect(screen.getByRole('button', {name: 'Open source in editor'})).toBeDisabled();
  await act(async () => release(wire({detail: 'Unavailable'}, 503)));
  await screen.findByText('Sources unavailable. No replacement or latest-source fallback.');
  expect(screen.getByRole('button', {name: 'Open source in editor'})).toBeDisabled();
  expect(screen.getByRole('region', {name: 'Source inspection'})).toHaveTextContent('Fixture file');
  expect(recentIds()).toEqual([]);
});

it('carries a chosen file through raw edit, reviewed XYZ proposal, fresh validation, durable save and explicit reopen in the real App', async () => {
  const original = 'env_name: reviewed_table\nembodiment: {id: robot, registry_name: franka}\nbackground:\n  id: desk\n  registry_name: table\n  params:\n    initial_pose:\n      position_xyz: [0.5, 0, 0] # meters\n      rotation_xyzw: [0, 0, 0, 1]\nobjects: []\nrelations: []\ntask: {composition: atomic, subtasks: [{kind: NoTask, params: {}}]}\n';
  const rawEdit = '# retained raw edit\n' + original;
  const candidate = rawEdit.replace('[0.5, 0, 0]', '[1.25, 0, 0]');
  const project = (yaml: string) => ({...projection(yaml), assets: [
    {id: 'robot', role: 'embodiment', registry_name: 'franka', properties: {id: 'robot', registry_name: 'franka', params: {}}},
    {id: 'desk', role: 'background', registry_name: 'table', properties: {id: 'desk', registry_name: 'table', params: {initial_pose: {position_xyz: [yaml === candidate ? 1.25 : 0.5, 0, 0], rotation_xyzw: [0, 0, 0, 1]}}}},
  ]});
  let accepted: Awaited<ReturnType<typeof makeReceipt>> | undefined;
  const fixture = setup('/library?layout=v7', (url, init) => {
    if (url === '/api/editor') return wire({default_document_id: 'fixture', documents: accepted ? [file, {...revisionRow, source_hash: hash(candidate)}] : [file], capabilities: {}, limitations: []});
    if (url === '/api/editor/documents/fixture') return wire({document_id: viewId, source: file.source, source_origin: {kind: 'discovered_file', id: 'fixture'}, yaml_text: original, source_hash: hash(original), validation: project(original)});
    if (url === '/api/editor/validate') return wire(project(JSON.parse(init!.body as string).yaml_text));
    if (url === '/api/editor/save') return makeReceipt(JSON.parse(init!.body as string)).then(receipt => {accepted = receipt; return wire(receipt);});
    if (url.includes('/editor/save-requests/')) return wire(accepted);
    if (url === `/api/editor/documents/${encodeURIComponent(revisionSource)}`) return wire({document_id: reopenedView, source: revisionSource, source_origin: {kind: 'editor_revision', id: revisionSource}, yaml_text: candidate, source_hash: hash(candidate), validation: project(candidate)});
  });
  fireEvent.click(await screen.findByRole('button', {name: 'Inspect Fixture file'}));
  fireEvent.click(screen.getByRole('button', {name: 'Open source in editor'}));
  await waitFor(() => expect(text()).toBe(original));
  const editor = screen.getByRole('textbox', {name: 'YAML editor'});
  edit(rawEdit);
  fireEvent.click(screen.getByRole('button', {name: 'Validate schema'}));
  await waitFor(() => expect(screen.getByRole('button', {name: 'Save durable revision'})).toBeEnabled());
  fireEvent.change(screen.getByLabelText('Authored asset'), {target: {value: 'desk'}});
  fireEvent.change(screen.getByLabelText('Proposed coordinate (m)'), {target: {value: '1.25'}});
  fireEvent.click(screen.getByRole('button', {name: 'Validate position proposal'}));
  await waitFor(() => expect(screen.getByRole('checkbox', {name: 'I reviewed this exact source diff'})).toBeEnabled());
  expect(text()).toBe(rawEdit);
  fireEvent.click(screen.getByRole('checkbox', {name: 'I reviewed this exact source diff'}));
  fireEvent.click(screen.getByRole('button', {name: 'Apply reviewed position'}));
  expect(text()).toBe(candidate);
  expect(screen.getByRole('button', {name: 'Save durable revision'})).toBeDisabled();
  await waitFor(() => expect(screen.getByRole('button', {name: 'Save durable revision'})).toBeEnabled(), {timeout: 3000});
  expect(fixture.fetcher.mock.calls.filter(([url]) => url === '/api/editor/validate').map(([, init]) => JSON.parse(init!.body as string))).toEqual([
    {yaml_text: rawEdit, document_id: viewId}, {yaml_text: candidate, document_id: viewId}, {yaml_text: candidate, document_id: viewId},
  ]);
  fireEvent.click(screen.getByRole('button', {name: 'Save durable revision'}));
  await screen.findByRole('button', {name: 'Open saved revision'});
  expect(accepted!.revision.yaml_text).toBe(candidate);
  expect(screen.getByLabelText('Document')).toHaveValue('fixture');
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', {name: 'Open saved revision'}));
  await waitFor(() => expect(screen.getByLabelText('Document')).toHaveValue(revisionSource));
  expect(screen.getByRole('textbox', {name: 'YAML editor'})).toBe(editor);
  expect(text()).toBe(candidate);
  expect(screen.getByRole('checkbox', {name: 'Automatic previews (GPU jobs)'})).not.toBeChecked();
  expect(screen.getByText(/Numbered draft saves are not supported here/)).toBeVisible();
  expect(fixture.fetcher.mock.calls.some(([url, init]) => init?.method === 'POST' && /generate|snapshots|versions|publications/.test(url))).toBe(false);
});

it('retains one editor and Library inspection across V7/legacy navigation while observing an accepted job without submission', async () => {
  const job = {id: 'accepted-refine', workspace_id: 'default', kind: 'generate', status: 'running', stage: 'generating', inputs: {operation: 'refine', base_yaml: source, document_id: viewId, input_hash: hash(source)}, result: null, error: null, created_at: 0, updated_at: 0, created_by_session_id: session.session_id};
  const pending = {payload: {...job.inputs, idempotency_key: 'accepted-once'}, job};
  sessionStorage.setItem('arena:editor:generate:v1', JSON.stringify(pending));
  let complete = false;
  const fixture = setup('/workspaces/default?layout=v7', url => {
    const observed = complete ? {...job, status: 'succeeded', stage: 'complete', result: {yaml_text: edited, validation: projection(edited), warnings: [], traces: [], publication: 'not_published'}} : job;
    if (url === '/api/workspaces/default') return wire({id: 'default', name: 'Workspace', jobs: [observed], event_cursor: complete ? 1 : 0});
    if (url === '/api/jobs/accepted-refine') return wire(observed);
  });
  await waitFor(() => expect(text()).toBe(source));
  const editor = screen.getByRole('textbox', {name: 'YAML editor'});
  edit(); fireEvent.change(screen.getByLabelText('Describe the environment and task'), {target: {value: 'retained prompt'}});
  fireEvent.click(screen.getByRole('link', {name: 'Library'}));
  fireEvent.click(await screen.findByRole('button', {name: 'Inspect Fixture file'}));
  fireEvent.change(screen.getByLabelText('Search library'), {target: {value: 'Fixture'}});
  const marker = fixture.fetcher.mock.calls.length;
  complete = true;
  await act(async () => { await fixture.cache.invalidateQueries({queryKey: ['editor-job']}); });
  expect(fixture.fetcher.mock.calls.slice(marker).some(([url]) => url === '/api/jobs/accepted-refine')).toBe(true);
  expect(fixture.fetcher.mock.calls.slice(marker).some(([url]) => /model-settings|previews|documents/.test(url))).toBe(false);
  // The existing workspace snapshot is refreshed explicitly; it is not a second observation owner.
  fireEvent.click(screen.getByRole('link', {name: 'Jobs & diagnostics'}));
  fireEvent.click(await screen.findByRole('button', {name: 'Refresh snapshot'}));
  await waitFor(() => expect(fixture.fetcher.mock.calls.some(([url]) => url === '/api/workspaces/default')).toBe(true));
  fireEvent.click(screen.getByRole('link', {name: 'Library'}));
  expect(await screen.findByLabelText('Search library')).toHaveValue('Fixture');
  expect(screen.getByRole('region', {name: 'Source inspection'})).toHaveTextContent('Fixture file');
  fireEvent.click(screen.getByRole('button', {name: 'Use legacy layout'}));
  await screen.findByRole('button', {name: 'Try V7 layout'});
  fireEvent.click(screen.getByRole('link', {name: 'Environment editor'}));
  await waitFor(() => expect(screen.getByRole('textbox', {name: 'YAML editor'})).toBe(editor));
  expect(text()).toBe(edited);
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('retained prompt');
  await screen.findByRole('button', {name: 'Apply generated YAML'});
  expect(screen.getByRole('checkbox', {name: 'Automatic previews (GPU jobs)'})).not.toBeChecked();
  expect(fixture.fetcher.mock.calls.filter(([url]) => url === '/api/sessions')).toHaveLength(1);
  expect(fixture.fetcher.mock.calls.some(([url, init]) => init?.method === 'POST' && /generate|snapshots|save|publications/.test(url))).toBe(false);
});

it('keeps older APIs on explicit legacy Save revision without claiming idempotent receipt recovery', async () => {
  const {fetcher} = setup('/workspaces/default?layout=v7', undefined, false);
  await waitFor(() => expect(screen.getByRole('button', {name: 'Save revision'})).toBeEnabled());
  expect(screen.getByText(/Legacy save has no idempotent receipt recovery/)).toBeVisible();
  expect(screen.queryByRole('button', {name: 'Save durable revision'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: 'Save revision'}));
  await screen.findByText(/Revision saved/);
  const saves = fetcher.mock.calls.filter(([url]) => url === '/api/editor/save');
  expect(saves).toHaveLength(1);
  expect(JSON.parse(saves[0][1]!.body as string)).toEqual({yaml_text: source, document_id: viewId, expected_source_hash: hash(source)});
  expect(fetcher.mock.calls.some(([url]) => url.includes('/save-requests/'))).toBe(false);
  expect(screen.getByRole('button', {name: 'Download current YAML'})).toBeEnabled();
});

it('rechecks source-open ownership after unsaved confirmation before dispatch', async () => {
  const fixture = setup('/workspaces/default');
  await waitFor(() => expect(text()).toBe(source)); edit();
  fireEvent.click(screen.getByRole('link', {name: 'Library'}));
  fireEvent.click(await screen.findByRole('button', {name: 'Inspect Fixture file'}));
  const before = fixture.fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/')).length;
  vi.spyOn(window, 'confirm').mockImplementation(() => {fixture.api.session = {...fixture.api.session!}; return true;});
  fireEvent.click(screen.getByRole('button', {name: 'Open source in editor'}));
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(before);
  expect(recentIds()).toEqual([]);
});

it('retires a pending source open on raw edit and releases loading without publishing its late response', async () => {
  let release!: (response: Response) => void;
  const fixture = setup('/workspaces/default', url => {
    if (url === '/api/editor') return wire({default_document_id: 'fixture', documents: [file, revisionRow], capabilities: {}, limitations: []});
    if (url === `/api/editor/documents/${encodeURIComponent(revisionSource)}`) return new Promise<Response>(resolve => {release = resolve;});
  });
  await waitFor(() => expect(text()).toBe(source));
  fireEvent.change(screen.getByLabelText('Document'), {target: {value: revisionSource}});
  await waitFor(() => expect(release).toBeTypeOf('function'));
  edit(edited);
  await act(async () => release(wire({document_id: reopenedView, source: revisionSource, source_origin: {kind: 'editor_revision', id: revisionSource}, yaml_text: edited, source_hash: hash(edited), validation: projection(edited)})));
  expect(text()).toBe(edited);
  expect(screen.getByLabelText('Document')).toHaveValue('fixture');
  expect(screen.getByLabelText('Document')).toBeEnabled();
  expect(recentIds()).toEqual([]);
  fireEvent.click(screen.getByRole('button', {name: 'Validate schema'}));
  await waitFor(() => expect(fixture.fetcher.mock.calls.some(([url]) => url === '/api/editor/validate')).toBe(true));
});

it.each(['index retirement', 'GET completion', 'confirmation'])('preserves sibling backup and rejects Open at %s', async boundary => {
  let release!: (response: Response) => void;
  const fixture = setup('/workspaces/default', url => {
    if (url === '/api/editor') return wire({default_document_id: 'fixture', documents: [file, revisionRow], capabilities: {}, limitations: []});
    if (url === `/api/editor/documents/${encodeURIComponent(revisionSource)}`) return new Promise<Response>(resolve => {release = resolve;});
  });
  await waitFor(() => expect(text()).toBe(source)); edit();
  const sibling = JSON.stringify({version: 1, documentId: 'fixture', viewId, sourceHash: hash(source), draft: 'sibling draft', prompt: 'sibling prompt'});
  vi.spyOn(window, 'confirm').mockImplementation(() => {if (boundary === 'confirmation') sessionStorage.setItem('arena.editor.draft.v1', sibling); return true;});
  fireEvent.change(screen.getByLabelText('Document'), {target: {value: revisionSource}});
  if (boundary === 'confirmation') {
    expect(release).toBeUndefined();
    expect(text()).toBe(edited);
    expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(sibling);
    return;
  }
  await waitFor(() => expect(release).toBeTypeOf('function'));
  sessionStorage.setItem('arena.editor.draft.v1', sibling);
  if (boundary === 'index retirement') await act(async () => {await fixture.cache.invalidateQueries({queryKey: ['editor']});});
  expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(sibling);
  await act(async () => release(wire({document_id: reopenedView, source: revisionSource, source_origin: {kind: 'editor_revision', id: revisionSource}, yaml_text: edited, source_hash: hash(edited), validation: projection(edited)})));
  expect(text()).toBe(edited);
  expect(screen.getByLabelText('Document')).toHaveValue('fixture');
  expect(recentIds()).toEqual([]);
  expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(sibling);
});

it.each(['remove', 'set', 'readback'])('StrictMode retains the recovery obligation across %s failure and warm remount', async fault => {
  const backup = {version: 1, documentId: 'fixture', viewId, sourceHash: hash(source), draft: 'recover these exact bytes', prompt: 'retained prompt'};
  const raw = JSON.stringify(backup); sessionStorage.setItem('arena.editor.draft.v1', raw);
  const fixture = setup('/workspaces/default', undefined, true, true);
  await waitFor(() => expect(screen.getByRole('button', {name: 'Restore draft'})).toBeEnabled());
  const getItem = Storage.prototype.getItem, setItem = Storage.prototype.setItem, removeItem = Storage.prototype.removeItem;
  let wrote = false;
  const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function(this: Storage, key, value) {
    if (key === 'arena.editor.draft.v1' && fault === 'set') throw new DOMException('quota', 'QuotaExceededError');
    setItem.call(this, key, value);
    if (key === 'arena.editor.draft.v1') wrote = true;
  });
  const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function(this: Storage, key) {
    if (key === 'arena.editor.draft.v1' && fault === 'readback' && wrote) throw new DOMException('denied', 'SecurityError');
    return getItem.call(this, key);
  });
  const remove = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(function(this: Storage, key) {
    if (key === 'arena.editor.draft.v1' && fault === 'remove') throw new DOMException('denied', 'SecurityError');
    removeItem.call(this, key);
  });
  fireEvent.click(screen.getByRole('button', {name: fault === 'remove' ? 'Discard recovered draft' : 'Restore draft'}));
  expect(text()).toBe(source);
  expect(screen.getByRole('button', {name: 'Download recovered YAML'})).toBeEnabled();
  await screen.findByText(/Memory-only mode/);
  set.mockRestore(); get.mockRestore(); remove.mockRestore();
  const persisted = sessionStorage.getItem('arena.editor.draft.v1');
  if (fault === 'readback') expect(JSON.parse(persisted!)).toMatchObject({version: 2, draft: backup.draft, prompt: backup.prompt});
  else expect(persisted).toBe(raw);
  const retained = fixture.cache.getQueryData<{storedBackup: string; getSnapshot: () => {recovery: unknown}}>(['editor-draft'])!;
  expect(retained.storedBackup).toBe(raw);
  fixture.unmount();
  render(<StrictMode><App api={fixture.api} cache={fixture.cache} history={fixture.history} makePort={() => null} /></StrictMode>);
  await screen.findByText(/Memory-only mode/);
  expect(retained.getSnapshot().recovery).toEqual(backup);
  edit(edited);
  expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(persisted);
  expect(screen.getByRole('button', {name: 'Download recovered YAML'})).toBeEnabled();
});

it('does not silently restart a retired initial load in memory-only mode after index refresh', async () => {
  let release!: (response: Response) => void;
  let pending = true;
  const fixture = setup('/workspaces/default', url => url.endsWith('/editor/documents/fixture') && pending ? new Promise<Response>(resolve => {release = resolve;}) : undefined);
  await waitFor(() => expect(release).toBeTypeOf('function'));
  const original = Storage.prototype.getItem;
  const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function(this: Storage, key) {
    if (key === 'arena.editor.draft.v1') throw new DOMException('denied', 'SecurityError');
    return original.call(this, key);
  });
  pending = false;
  await act(async () => release(wire({document_id: viewId, source: file.source, source_origin: {kind: file.kind, id: file.id}, yaml_text: source, source_hash: hash(source), validation: projection(source)})));
  expect(text()).toBe('');
  await screen.findByText(/Memory-only mode/);
  const query = fixture.cache.getQueryCache().find({queryKey: ['editor'], exact: false})!;
  act(() => fixture.cache.setQueryData(query.queryKey, {...query.state.data!, limitations: ['refreshed catalogue']}));
  await screen.findByText('refreshed catalogue');
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/documents/fixture'))).toHaveLength(1);
  expect(text()).toBe('');
  fireEvent.change(screen.getByLabelText('Document'), {target: {value: 'fixture'}});
  await waitFor(() => expect(text()).toBe(source));
  get.mockRestore();
  expect(sessionStorage.getItem('arena.editor.draft.v1')).toBeNull();
});

it('does not let a retained prompt handler edit the authoritative controller after warm remount', async () => {
  const fixture = setup('/workspaces/default');
  await waitFor(() => expect(text()).toBe(source));
  const prompt = screen.getByLabelText('Describe the environment and task');
  const retained = (prompt as unknown as Record<string, {onChange: (e: {target: {value: string}}) => void}>)[Object.keys(prompt).find(key => key.startsWith('__reactProps$'))!].onChange;
  fixture.unmount();
  render(<App api={fixture.api} cache={fixture.cache} history={fixture.history} makePort={() => null} />);
  await waitFor(() => expect(text()).toBe(source));
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), {target: {value: 'current prompt'}});
  const backup = sessionStorage.getItem('arena.editor.draft.v1');
  act(() => retained({target: {value: 'retired prompt'}}));
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('current prompt');
  expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(backup);
});

it.each(['navigation', 'navigation ABA', 'current stream'])('fences retained native input lifetime without breaking same-render streams: %s', async boundary => {
  const fixture = setup('/workspaces/default');
  await waitFor(() => expect(text()).toBe(source));
  const prompt = screen.getByLabelText('Describe the environment and task');
  const captured = (prompt as unknown as Record<string, {onChange: (event: {target: {value: string}}) => void}>)[Object.keys(prompt).find(key => key.startsWith('__reactProps$'))!].onChange;
  if (boundary.startsWith('navigation')) {
    fireEvent.click(screen.getByRole('link', {name: 'Library'}));
    await screen.findByRole('heading', {name: 'Library'});
    if (boundary.endsWith('ABA')) {fireEvent.click(screen.getByRole('link', {name: 'Environment editor'})); await screen.findByRole('heading', {name: 'ArenaEnvGraphSpec live editor'});}
  }
  const controller = fixture.cache.getQueryData<DraftController>(['editor-draft'])!;
  const before = controller.getSnapshot();
  const backup = sessionStorage.getItem('arena.editor.draft.v1');
  act(() => {captured({target: {value: 'first event'}}); captured({target: {value: 'second event'}});});
  if (boundary === 'current stream') expect(controller.getSnapshot().prompt).toBe('second event');
  else {
    expect(controller.getSnapshot().prompt).toBe(before.prompt);
    expect(controller.getSnapshot().revision).toBe(before.revision);
    expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(backup);
  }
});

it.each(['initial error', 'refresh error', 'refresh success', 'invalidate'])('keeps exact research recovery independent of mutable catalogue availability: %s', async boundary => {
  const identity = {store_id: 'local', reservation_id: '4'.repeat(32), revision_id: '5'.repeat(32), family: 'Example', version: 2, manifest_digest: '6'.repeat(64), source: {kind: 'editor_revision', schema_version: 1, editor_revision_id: revisionId, source_hash: hash(source), canonical_hash: canonical, bundle_codec: 'arena-editor-bundle/v1', bundle_sha256: '8'.repeat(64), receipt_sha256: '9'.repeat(64)}};
  const descriptor = `research-version:local:${identity.reservation_id}:${identity.manifest_digest}`;
  const raw = JSON.stringify({version: 1, documentId: descriptor, viewId, sourceHash: hash(source), draft: edited, prompt: 'exact recovery', researchIdentity: identity});
  sessionStorage.setItem('arena.editor.draft.v1', raw);
  const releases: ((response: Response) => void)[] = [];
  let failed = boundary === 'initial error', refreshed = false;
  const fixture = setup('/workspaces/default', url => {
    if (url === '/api/editor') return failed ? wire({detail: 'catalogue unavailable'}, 503) : wire({documents: [file], capabilities: {research_version_open: false}, limitations: refreshed ? ['research-independent refresh'] : []});
    if (url === `/api/editor/documents/${encodeURIComponent(descriptor)}`) return new Promise<Response>(resolve => releases.push(resolve));
  });
  await waitFor(() => expect(releases).toHaveLength(1));
  const query = fixture.cache.getQueryCache().find({queryKey: ['editor'], exact: false})!;
  if (boundary.startsWith('refresh')) {
    failed = boundary === 'refresh error'; refreshed = true;
    await act(async () => {await fixture.cache.invalidateQueries({queryKey: query.queryKey});});
    await screen.findByText(failed ? 'Editor API unavailable' : 'research-independent refresh');
  }
  if (boundary === 'invalidate') act(() => {void fixture.cache.invalidateQueries({queryKey: query.queryKey, refetchType: 'none'});});
  expect(releases).toHaveLength(1);
  await act(async () => releases[0](wire({document_id: reopenedView, source: descriptor, source_origin: {kind: 'research_version', id: descriptor}, research_identity: identity, yaml_text: source, source_hash: hash(source), validation: projection(source)})));
  await waitFor(() => expect(screen.getByRole('button', {name: 'Restore draft'})).toBeEnabled());
  expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(raw);
  fireEvent.click(screen.getByRole('button', {name: 'Restore draft'}));
  expect(text()).toBe(edited);
  expect(JSON.parse(sessionStorage.getItem('arena.editor.draft.v1')!)).toMatchObject({documentId: descriptor, viewId: reopenedView, researchIdentity: identity, draft: edited});
  expect(recentIds()).toEqual([]);
});

it.each(['typed default', 'legacy default', 'legacy choice', 'file recovery'].flatMap(entry =>
  ['invalidate', 'refresh error', 'refresh success', 'late error', 'current'].map(boundary => ({entry, boundary}))))('fences catalogue-dependent $entry load at $boundary and permits only explicit retry', async ({entry, boundary}) => {
  const key = 'arena.editor.draft.v1';
  const legacy = entry.startsWith('legacy');
  const row = legacy ? {id: file.id, name: file.name, source: file.source} : file;
  const metadata = {default_document_id: entry === 'legacy choice' ? '' : 'fixture', documents: [row], capabilities: {}, limitations: [] as string[]};
  const doc = {document_id: viewId, source: file.source, ...(legacy ? {} : {source_origin: {kind: file.kind, id: file.id}}), yaml_text: source, source_hash: hash(source), validation: projection(source)};
  const raw = entry === 'file recovery' ? JSON.stringify({version: 1, documentId: 'fixture', viewId, sourceHash: hash(source), draft: edited, prompt: 'recover exactly'}) : null;
  if (raw) sessionStorage.setItem(key, raw);
  let release!: (response: Response) => void, failed = false, first = true;
  const fixture = setup('/workspaces/default', url => {
    if (url === '/api/editor') return failed ? wire({detail: 'catalogue refetch failed'}, 503) : wire(metadata);
    if (url.endsWith('/editor/documents/fixture')) {
      if (first) {first = false; return new Promise<Response>(resolve => {release = resolve;});}
      return wire(doc);
    }
  });
  await screen.findByRole('option', {name: 'Fixture file'});
  if (entry === 'legacy choice') fireEvent.change(screen.getByLabelText('Document'), {target: {value: 'fixture'}});
  await waitFor(() => expect(release).toBeTypeOf('function'));
  const query = fixture.cache.getQueryCache().find({queryKey: ['editor'], exact: false})!;
  expect(query).toBeDefined();
  if (boundary === 'refresh error') {
    failed = true;
    await act(async () => {await fixture.cache.invalidateQueries({queryKey: query.queryKey});});
    await screen.findByText('Editor API unavailable');
  } else if (boundary === 'refresh success') {
    metadata.limitations = ['catalogue refreshed'];
    await act(async () => {await fixture.cache.invalidateQueries({queryKey: query.queryKey});});
    await screen.findByText('catalogue refreshed');
  } else if (boundary !== 'current') act(() => {void fixture.cache.invalidateQueries({queryKey: query.queryKey, refetchType: 'none'});});
  await act(async () => release(boundary === 'late error' ? wire({detail: 'retired document failure'}, 503) : wire(doc)));
  if (boundary === 'current') {await waitFor(() => expect(text()).toBe(source)); expect(recentIds()).toEqual([]); return;}
  expect(text()).toBe('');
  expect(fixture.cache.getQueryData<DraftController>(['editor-draft'])!.validation).toBeNull();
  expect(screen.queryByText('retired document failure')).not.toBeInTheDocument();
  expect(sessionStorage.getItem(key)).toBe(raw);
  expect(screen.getByLabelText('Document')).toBeEnabled();
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(1);
  failed = false;
  act(() => fixture.cache.setQueryData(query.queryKey, {...metadata, limitations: ['fresh metadata permits retry']}));
  await screen.findByText('fresh metadata permits retry');
  expect(text()).toBe('');
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(1);
  fireEvent.change(screen.getByLabelText('Document'), {target: {value: 'fixture'}});
  await waitFor(() => expect(text()).toBe(source));
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(2);
  if (raw) expect(sessionStorage.getItem(key)).toBe(raw);
});

function retainedClick(button: HTMLElement) {
  return (button as unknown as Record<string, {onClick: () => void}>)[Object.keys(button).find(key => key.startsWith('__reactProps$'))!].onClick;
}
it.each(['Restore draft', 'Discard recovered draft', 'Review stored backup', 'Discard stored backup', 'Apply generated YAML'].flatMap(action =>
  ['navigation', 'navigation ABA', 'session before render', 'session rendered', 'client', 'current'].map(boundary => ({action, boundary}))))('retires mounted disposition authority for $action at $boundary', async ({action, boundary}) => {
  const key = 'arena.editor.draft.v1';
  const invalid = action === 'Review stored backup' || action === 'Discard stored backup';
  const generated = action === 'Apply generated YAML';
  if (!generated) sessionStorage.setItem(key, invalid ? '{invalid backup' : JSON.stringify({version: 1, documentId: 'fixture', viewId, sourceHash: hash(source), draft: edited, prompt: 'recovery prompt'}));
  const job = {id: 'accepted-review', workspace_id: 'default', kind: 'generate', status: 'succeeded', stage: 'complete', inputs: {operation: 'new'}, result: {yaml_text: edited, validation: projection(edited)}, error: null, created_at: 0, updated_at: 0, created_by_session_id: session.session_id};
  const pending = JSON.stringify({payload: {...job.inputs, idempotency_key: 'accepted-once'}, job});
  if (generated) sessionStorage.setItem('arena:editor:generate:v1', pending);
  const fixture = setup('/workspaces/default', url => {
    if (generated && url === '/api/workspaces/default') return wire({id: 'default', name: 'Workspace', jobs: [job], event_cursor: 0});
    if (url === '/api/jobs/accepted-review') return wire(job);
  });
  await screen.findByRole('option', {name: 'Fixture file'});
  if (!invalid) await waitFor(() => expect(text()).toBe(source));
  if (action === 'Discard stored backup') fireEvent.click(screen.getByRole('button', {name: 'Review stored backup'}));
  const button = await screen.findByRole('button', {name: action});
  expect(button).toBeEnabled();
  const captured = retainedClick(button);
  const controller = fixture.cache.getQueryData<DraftController>(['editor-draft'])!;
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
  if (boundary.startsWith('navigation')) {
    fireEvent.click(screen.getByRole('link', {name: 'Library'}));
    await screen.findByRole('heading', {name: 'Library'});
    if (boundary.endsWith('ABA')) {fireEvent.click(screen.getByRole('link', {name: 'Environment editor'})); await screen.findByRole('heading', {name: 'ArenaEnvGraphSpec live editor'});}
  }
  if (boundary.startsWith('session')) {fixture.api.session = {...fixture.api.session!}; if (boundary === 'session rendered') fixture.redraw();}
  if (boundary === 'client') {fixture.redraw(new ApiClient(fixture.fetcher as typeof fetch)); await waitFor(() => expect(fixture.fetcher.mock.calls.filter(([u]) => u === '/api/sessions')).toHaveLength(2));}
  const before = controller.getSnapshot();
  const bytes = sessionStorage.getItem(key);
  act(captured);
  if (boundary === 'current') expect(controller.getSnapshot().revision).toBeGreaterThan(before.revision);
  else {
    expect(controller.getSnapshot().revision).toBe(before.revision);
    expect(controller.getSnapshot().draft).toBe(before.draft);
    expect(controller.getSnapshot().recovery).toBe(before.recovery);
    expect(sessionStorage.getItem(key)).toBe(bytes);
    expect(confirm).not.toHaveBeenCalled();
    // Retired UI is not a permanent lock: only a replacement rendered control
    // receives the current navigation/session/client authority.
    if (boundary === 'navigation') fireEvent.click(screen.getByRole('link', {name: 'Environment editor'}));
    if (boundary.startsWith('session')) fixture.redraw();
    await waitFor(() => {
      const fresh = screen.getByRole('button', {name: action});
      expect(fresh).toBeEnabled();
      expect(retainedClick(fresh)).not.toBe(captured);
    });
    const revision = controller.getSnapshot().revision;
    fireEvent.click(screen.getByRole('button', {name: action}));
    expect(controller.getSnapshot().revision).toBeGreaterThan(revision);
  }
  if (generated) expect(sessionStorage.getItem('arena:editor:generate:v1')).toBe(pending);
  expect(fixture.fetcher.mock.calls.some(([u, i]) => i?.method === 'POST' && /generate|snapshots|save|versions|publication/.test(u))).toBe(false);
});

it.each(['raw', 'prompt', 'raw ABA', 'prompt ABA', 'pristine'])('does not grant delayed metadata replacement consent over local authoring: %s', async mode => {
  let release!: (response: Response) => void;
  const fixture = setup('/workspaces/default', url => url === '/api/editor' ? new Promise<Response>(resolve => {release = resolve;}) : undefined);
  await waitFor(() => expect(release).toBeTypeOf('function'));
  if (mode.startsWith('raw')) {edit(edited); if (mode.endsWith('ABA')) edit('');}
  if (mode.startsWith('prompt')) {
    fireEvent.change(screen.getByLabelText('Describe the environment and task'), {target: {value: 'my prompt'}});
    if (mode.endsWith('ABA')) fireEvent.change(screen.getByLabelText('Describe the environment and task'), {target: {value: ''}});
  }
  await act(async () => release(wire({default_document_id: 'fixture', documents: [file], capabilities: {}, limitations: ['delayed metadata arrived']})));
  await screen.findByText('delayed metadata arrived');
  if (mode === 'pristine') {await waitFor(() => expect(text()).toBe(source)); return;}
  expect(text()).toBe(mode === 'raw' ? edited : '');
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue(mode === 'prompt' ? 'my prompt' : '');
  expect(screen.getByLabelText('Document')).toHaveValue('');
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(0);
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  fireEvent.change(screen.getByLabelText('Document'), {target: {value: 'fixture'}});
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(0);
  confirm.mockReturnValue(true);
  fireEvent.change(screen.getByLabelText('Document'), {target: {value: 'fixture'}});
  await waitFor(() => expect(text()).toBe(source));
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(1);
});

it.each(['invalid', 'valid'])('requires detachment consent for pre-load dirty Discard without rearming a source GET: %s', async kind => {
  const key = 'arena.editor.draft.v1';
  const raw = kind === 'invalid' ? '{unknown backup' : JSON.stringify({version: 1, documentId: 'fixture', viewId, sourceHash: hash(source), draft: 'old recovery', prompt: 'old prompt'});
  sessionStorage.setItem(key, raw);
  let release!: (response: Response) => void;
  const fixture = setup('/workspaces/default', url => url.endsWith('/editor/documents/fixture') ? new Promise<Response>(resolve => {release = resolve;}) : undefined);
  await screen.findByRole('option', {name: 'Fixture file'});
  if (kind === 'valid') await waitFor(() => expect(release).toBeTypeOf('function'));
  edit(edited);
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), {target: {value: 'keep current prompt'}});
  if (kind === 'invalid') fireEvent.click(screen.getByRole('button', {name: 'Review stored backup'}));
  const action = kind === 'invalid' ? 'Discard stored backup' : 'Discard recovered draft';
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  fireEvent.click(screen.getByRole('button', {name: action}));
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(sessionStorage.getItem(key)).toBe(raw);
  expect(text()).toBe(edited);
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', {name: action}));
  expect(screen.getByLabelText('Document')).toHaveValue('local:new-environment');
  expect(JSON.parse(sessionStorage.getItem(key)!)).toMatchObject({documentId: 'local:new-environment', viewId: 'local:new-environment', sourceHash: '', draft: edited, prompt: 'keep current prompt'});
  if (kind === 'valid') await act(async () => release(wire({document_id: viewId, source: file.source, source_origin: {kind: file.kind, id: file.id}, yaml_text: source, source_hash: hash(source), validation: projection(source)})));
  expect(text()).toBe(edited);
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(kind === 'valid' ? 1 : 0);
  const blobs: Blob[] = [];
  vi.spyOn(URL, 'createObjectURL').mockImplementation(blob => {blobs.push(blob as Blob); return 'blob:preload-draft';});
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  fireEvent.click(screen.getByRole('button', {name: 'Download current YAML'}));
  expect(blobs).toHaveLength(1);
  const downloaded = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsText(blobs[0]);
  });
  expect(downloaded).toBe(edited);
  confirm.mockReturnValue(false);
  fireEvent.change(screen.getByLabelText('Document'), {target: {value: 'fixture'}});
  expect(text()).toBe(edited);
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(kind === 'valid' ? 1 : 0);
});

it('requires explicit Review and Discard of malformed bytes before the initial source can load', async () => {
  sessionStorage.setItem('arena.editor.draft.v1', '{unknown backup');
  const fixture = setup('/workspaces/default');
  await screen.findByText(/Export your YAML before reloading/);
  expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe('{unknown backup');
  expect(fixture.fetcher.mock.calls.some(([url]) => url.includes('/editor/documents/'))).toBe(false);
  fireEvent.click(screen.getByRole('button', {name: 'Review stored backup'}));
  expect(screen.getByRole('button', {name: 'Download stored backup'})).toBeEnabled();
  fireEvent.click(screen.getByRole('button', {name: 'Discard stored backup'}));
  await waitFor(() => expect(text()).toBe(source));
  expect(sessionStorage.getItem('arena.editor.draft.v1')).toBeNull();
  expect(recentIds()).toEqual([]);
});

it.each(['Restore draft', 'Discard recovered draft'])('keeps recovery and current inputs when %s meets a replaced backup', async action => {
  const backup = {version: 1, documentId: 'fixture', viewId, sourceHash: hash(source), draft: 'recover me', prompt: 'recovery prompt'};
  sessionStorage.setItem('arena.editor.draft.v1', JSON.stringify(backup));
  setup('/workspaces/default');
  await waitFor(() => expect(screen.getByRole('button', {name: 'Restore draft'})).toBeEnabled());
  const sibling = JSON.stringify({...backup, draft: 'sibling'});
  sessionStorage.setItem('arena.editor.draft.v1', sibling);
  fireEvent.click(screen.getByRole('button', {name: action}));
  expect(text()).toBe(source);
  expect(screen.getByRole('button', {name: 'Download recovered YAML'})).toBeEnabled();
  expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(sibling);
  expect(screen.getByText(/Export your YAML before reloading/)).toBeVisible();
});

it('keeps retained A bound to its original backup after a warm QueryClient remount over sibling B', async () => {
  const fixture = setup('/workspaces/default');
  await waitFor(() => expect(text()).toBe(source)); edit();
  const controller = fixture.cache.getQueryData(['editor-draft']);
  fixture.unmount();
  const sibling = JSON.stringify({version: 1, documentId: 'fixture', viewId, sourceHash: hash(source), draft: 'sibling B', prompt: 'B'});
  sessionStorage.setItem('arena.editor.draft.v1', sibling);
  render(<App api={fixture.api} cache={fixture.cache} history={fixture.history} makePort={() => null} />);
  await screen.findByText(/Export your YAML before reloading/);
  expect(fixture.cache.getQueryData(['editor-draft'])).toBe(controller);
  expect(text()).toBe(edited);
  edit(edited + '# memory only');
  expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(sibling);
  fireEvent.click(screen.getByRole('button', {name: 'Review stored backup'}));
  expect(text()).toBe(edited + '# memory only');
  expect(screen.getByRole('button', {name: 'Restore draft'})).toBeEnabled();
  expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(sibling);
  fireEvent.click(screen.getByRole('button', {name: 'Discard recovered draft'}));
  expect(JSON.parse(sessionStorage.getItem('arena.editor.draft.v1')!).draft).toBe(edited + '# memory only');
  expect(screen.queryByRole('button', {name: 'Restore draft'})).not.toBeInTheDocument();
});

it('rejects a retained document-change handler after same-turn raw draft ABA', async () => {
  const fixture = setup('/workspaces/default', url => url === '/api/editor' ? wire({default_document_id: 'fixture', documents: [file, revisionRow], capabilities: {}, limitations: []}) : undefined);
  await waitFor(() => expect(text()).toBe(source));
  const select = screen.getByLabelText('Document');
  const key = Object.keys(select).find(key => key.startsWith('__reactProps$'))!;
  const change = (select as unknown as Record<string, {onChange: (event: {target: {value: string}}) => void}>)[key].onChange;
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', {name: 'YAML editor'}))!;
  act(() => {
    cm.dispatch({changes: {from: 0, to: cm.state.doc.length, insert: edited}});
    cm.dispatch({changes: {from: 0, to: cm.state.doc.length, insert: source}});
    change({target: {value: revisionSource}});
  });
  expect(fixture.fetcher.mock.calls.some(([url]) => url === `/api/editor/documents/${encodeURIComponent(revisionSource)}`)).toBe(false);
});

it.each(['session success', 'session error', 'client success', 'client error'])('remounts Library for data-owner retirement and drops late Open %s', async retirement => {
  let release!: (response: Response) => void;
  const fixture = setup('/library', url => url.endsWith('/editor/documents/fixture') ? new Promise<Response>(resolve => {release = resolve;}) : undefined);
  fireEvent.click(await screen.findByRole('button', {name: 'Inspect Fixture file'}));
  const oldSearch = screen.getByLabelText('Search library');
  fireEvent.change(oldSearch, {target: {value: 'Fixture'}});
  fireEvent.click(screen.getByRole('button', {name: 'Open source in editor'}));
  await waitFor(() => expect(release).toBeTypeOf('function'));
  if (retirement.startsWith('session')) {fixture.api.session = {...fixture.api.session!}; fixture.redraw();}
  else fixture.redraw(new ApiClient(fixture.fetcher as typeof fetch));
  await waitFor(() => expect(screen.getByLabelText('Search library')).not.toBe(oldSearch));
  expect(screen.getByLabelText('Search library')).toHaveValue('');
  await screen.findByRole('button', {name: 'Inspect Fixture file'});
  await act(async () => release(retirement.endsWith('error') ? wire({detail: 'retired open'}, 409) : wire({document_id: viewId, source: file.source, source_origin: {kind: file.kind, id: file.id}, yaml_text: source, source_hash: hash(source), validation: projection(source)})));
  expect(screen.queryByText('retired open')).not.toBeInTheDocument();
  expect(recentIds()).toEqual([]);
  expect(screen.getByRole('heading', {name: 'Library'})).toBeVisible();
});

it('quarantines a duplicated default identity before either editor selection or document loading', async () => {
  const {fetcher} = setup('/workspaces/default', url => url === '/api/editor' ? wire({default_document_id: 'fixture', documents: [file, {...file, source: null}], capabilities: {}, limitations: []}) : undefined);
  await waitFor(() => expect(screen.getByLabelText('Document')).toBeEnabled());
  expect(screen.queryByRole('option', {name: 'Fixture file'})).not.toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url.includes('/editor/documents/'))).toBe(false);
  expect(text()).toBe('');
});

it('rejects an oversized catalogue as unavailable rather than truncating away an ambiguous duplicate', async () => {
  const documents = [file, ...Array.from({length: 2047}, (_, i) => ({...file, id: `file-${i}`})), {...file, source: 'duplicate.yaml'}];
  const {fetcher} = setup('/library', url => url === '/api/editor' ? wire({default_document_id: 'fixture', documents, capabilities: {}, limitations: []}) : undefined);
  await screen.findByText('Sources unavailable. No replacement or latest-source fallback.');
  expect(screen.queryByRole('button', {name: 'Inspect Fixture file'})).not.toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => /documents|model-settings|previews/.test(url))).toBe(false);
});

it.each(['retained handler', 'confirmation'])('rejects same-turn catalogue hash ABA before dispatch through %s', async phase => {
  const fixture = setup(phase === 'confirmation' ? '/workspaces/default' : '/library');
  if (phase === 'confirmation') {
    await waitFor(() => expect(text()).toBe(source)); edit();
    fireEvent.click(screen.getByRole('link', {name: 'Library'}));
  }
  fireEvent.click(await screen.findByRole('button', {name: 'Inspect Fixture file'}));
  const button = screen.getByRole('button', {name: 'Open source in editor'});
  expect(button).toBeEnabled();
  const key = Object.keys(button).find(key => key.startsWith('__reactProps$'))!;
  const captured = (button as unknown as Record<string, {onClick: () => void}>)[key].onClick;
  const query = fixture.cache.getQueryCache().find({queryKey: ['editor'], exact: false})!;
  const original = query.state.data as {documents: unknown[]};
  const aba = () => {
    fixture.cache.setQueryData(query.queryKey, {...original, documents: [{...file, source_hash: hash(edited)}]});
    fixture.cache.setQueryData(query.queryKey, original);
  };
  const count = fixture.fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/')).length;
  if (phase === 'confirmation') vi.spyOn(window, 'confirm').mockImplementation(() => {aba(); return true;});
  act(() => {if (phase === 'retained handler') aba(); captured();});
  await act(async () => {await new Promise(resolve => setTimeout(resolve, 30));});
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(count);
  expect(recentIds()).toEqual([]);
});

it.each([0, 1])('checks the inclusive 2MiB catalogue UTF-8 envelope boundary (+%i byte)', async extra => {
  const index = {default_document_id: 'fixture', documents: [file], capabilities: {}, limitations: [], padding: 'é'};
  index.padding += 'x'.repeat(2 * 1024 * 1024 - new TextEncoder().encode(JSON.stringify(index)).length + extra);
  expect(new TextEncoder().encode(JSON.stringify(index))).toHaveLength(2 * 1024 * 1024 + extra);
  const fixture = setup('/library', url => url === '/api/editor' ? wire(index) : undefined);
  if (extra) {
    await screen.findByText('Sources unavailable. No replacement or latest-source fallback.');
    expect(screen.queryByRole('button', {name: 'Inspect Fixture file'})).not.toBeInTheDocument();
  } else expect(await screen.findByRole('button', {name: 'Inspect Fixture file'})).toBeEnabled();
  expect(fixture.fetcher.mock.calls.some(([url]) => /documents|model-settings|previews/.test(url))).toBe(false);
});

it('withholds a mismatched typed default load before publishing draft or validation', async () => {
  setup('/workspaces/default', url => url.endsWith('/editor/documents/fixture') ? wire({document_id: viewId, source: file.source, source_origin: {kind: file.kind, id: 'wrong'}, yaml_text: source, source_hash: hash(source), validation: projection(source)}) : undefined);
  await screen.findByText(/Source identity or hash verification failed/);
  expect(text()).toBe('');
  expect(screen.getByRole('button', {name: 'Save durable revision'})).toBeDisabled();
  expect(recentIds()).toEqual([]);
});
