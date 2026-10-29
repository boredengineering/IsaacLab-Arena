import { createHash, webcrypto } from 'node:crypto';
import { flushSync } from 'react-dom';
import type { DraftController } from './draft-controller';
import { AuthoredInspector } from './authored-inspector';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { EditorView as CodeMirrorView } from '@codemirror/view';
import { beforeEach, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { EditorView, type EditorViewProps } from './editor';
import { RuntimeProvider } from './runtime';
import { ThemeProvider } from './theme';
import { createMemoryHistory, createRootRoute, createRouter, RouterContextProvider } from '@tanstack/react-router';
import { App } from './app';
import { ApiClient } from './api';
import { PROVIDERS } from './model-settings-contracts';

const response = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status });
beforeEach(() => sessionStorage.clear());

const noPort = () => null;
const positionSource = '# untouched\nenv_name: reviewed_table\nembodiment: {id: robot, registry_name: franka}\nbackground:\n  id: desk\n  registry_name: table\n  params:\n    initial_pose:\n      position_xyz: [0.5, 0, 0] # meters\n      rotation_xyzw: [0, 0, 0, 1]\nobjects: []\nrelations: []\ntask: {composition: atomic, subtasks: [{kind: NoTask, params: {}}]}\n';
const positionCandidate = positionSource.replace('[0.5, 0, 0]', '[1.25, 0, 0]');
const positionHash = (text: string) => createHash('sha256').update(text).digest('hex');
function positionProjection(text: string) {
  const entries = [
    {id: 'robot', registry_name: 'franka', role: 'embodiment', params: {}},
    {id: 'desk', registry_name: 'table', role: 'background', params: {initial_pose: {position_xyz: [text === positionCandidate ? 1.25 : 0.5, 0, 0], rotation_xyzw: [0, 0, 0, 1]}}},
  ];
  const assets = entries.map(({role, ...properties}) => ({...properties, role, properties}));
  return {...validation, source_hash: positionHash(text), assets, relations: [], reified_relations: [], tasks: [{kind: 'NoTask', params: {}}], graph: {nodes: [], edges: []}};
}
function positionServer() {
  const base = editorServer();
  const releases: ((r: Response) => void)[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({...await (await base(url, init)).json(), documents: [{id: 'fixture', name: 'Fixture', source: 'tests/review.yaml'}, {id: 'other', name: 'Other', source: 'tests/other.yaml'}]});
    if (url.includes('/editor/documents/')) return response({document_id: 'frozen-position', source: 'tests/review.yaml', yaml_text: positionSource, source_hash: positionHash(positionSource), validation: positionProjection(positionSource)});
    if (url.endsWith('/editor/validate')) return new Promise<Response>(resolve => releases.push(resolve));
    return base(url, init);
  });
  return {fetcher, releases};
}
function retainedChange(node: HTMLElement) {
  const key = Object.keys(node).find(key => key.startsWith('__reactProps$'))!;
  return (node as unknown as Record<string, {onChange: (event: {target: {value: string}}) => void}>)[key].onChange;
}
it.each(['Apply generated YAML', 'Discard stored backup'].flatMap(action =>
  ['navigation', 'navigation ABA', 'session', 'client', 'input ABA', 'current'].map(boundary => ({action, boundary}))))('rechecks $action authority after confirmation changes $boundary', async ({action, boundary}) => {
  const discard = action === 'Discard stored backup';
  const key = 'arena.editor.draft.v1';
  if (discard) sessionStorage.setItem(key, '{unreviewed backup');
  const job = {id: 'generated-confirm', workspace_id: 'default', kind: 'generate', status: 'succeeded', stage: 'complete', created_at: 0, updated_at: 0, created_by_session_id: 's', error: null,
    inputs: {operation: 'new'}, result: {yaml_text: positionCandidate, validation: positionProjection(positionCandidate)}};
  if (!discard) sessionStorage.setItem('arena:editor:generate:v1', JSON.stringify({payload: {...job.inputs, idempotency_key: 'retained'}, job}));
  const base = positionServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (!discard && url.endsWith('/workspaces/default')) return response({id: 'default', name: 'Arena', event_cursor: 0, jobs: [job]});
    if (url.endsWith('/jobs/generated-confirm')) return response(job);
    return base.fetcher(url, init);
  });
  const view = mountPersistentEditor(fetcher);
  await screen.findByRole('option', {name: 'Fixture'});
  const controller = view.cache.getQueryData<DraftController>(['editor-draft'])!;
  if (discard) {
    fireEvent.change(screen.getByLabelText('Describe the environment and task'), {target: {value: 'keep unbound prompt'}});
    fireEvent.click(screen.getByRole('button', {name: 'Review stored backup'}));
  } else await waitFor(() => expect(controller.getSnapshot().draft).toBe(positionSource));
  const button = await screen.findByRole('button', {name: action});
  let afterConfirmation = controller.getSnapshot(), bytes = sessionStorage.getItem(key);
  const confirm = vi.spyOn(window, 'confirm').mockImplementation(() => {
    if (boundary.startsWith('navigation')) {
      flushSync(() => view.setProps({active: false}));
      if (boundary.endsWith('ABA')) flushSync(() => view.setProps({active: true}));
    }
    if (boundary === 'session') view.api.session = {...view.api.session!};
    if (boundary === 'client') flushSync(() => view.setApi(new ApiClient(fetcher as typeof fetch)));
    if (boundary === 'input ABA') {
      const change = retainedChange(screen.getByLabelText('Describe the environment and task'));
      const original = controller.getSnapshot().prompt;
      change({target: {value: 'intervening prompt'}}); change({target: {value: original}});
    }
    afterConfirmation = controller.getSnapshot(); bytes = sessionStorage.getItem(key);
    return true;
  });
  fireEvent.click(button);
  expect(confirm).toHaveBeenCalledTimes(1);
  if (boundary === 'current') expect(controller.getSnapshot().revision).toBeGreaterThan(afterConfirmation.revision);
  else {
    expect(controller.getSnapshot().revision).toBe(afterConfirmation.revision);
    expect(controller.getSnapshot().documentId).toBe(afterConfirmation.documentId);
    expect(controller.getSnapshot().draft).toBe(afterConfirmation.draft);
    expect(controller.getSnapshot().recovery).toBe(afterConfirmation.recovery);
    expect(sessionStorage.getItem(key)).toBe(bytes);
  }
});

it.each(['catalogue before', 'catalogue confirmation', 'navigation confirmation', 'session confirmation', 'client confirmation', 'current'])('fences legacy selection before and after confirmation: %s', async boundary => {
  const {fetcher} = positionServer();
  const view = mountPersistentEditor(fetcher);
  const cm = () => CodeMirrorView.findFromDOM(screen.getByRole('textbox', {name: 'YAML editor'}))!;
  await waitFor(() => expect(cm().state.doc.toString()).toBe(positionSource));
  act(() => cm().dispatch({changes: {from: 0, to: cm().state.doc.length, insert: positionCandidate}}));
  const select = retainedChange(screen.getByLabelText('Document'));
  const controller = view.cache.getQueryData<DraftController>(['editor-draft'])!;
  const query = view.cache.getQueryCache().find({queryKey: ['editor'], exact: false})!;
  const invalidate = () => {void view.cache.invalidateQueries({queryKey: query.queryKey, refetchType: 'none'});};
  const confirm = vi.spyOn(window, 'confirm').mockImplementation(() => {
    if (boundary === 'catalogue confirmation') invalidate();
    if (boundary === 'navigation confirmation') flushSync(() => view.setProps({active: false}));
    if (boundary === 'session confirmation') view.api.session = {...view.api.session!};
    if (boundary === 'client confirmation') flushSync(() => view.setApi(new ApiClient(fetcher as typeof fetch)));
    return true;
  });
  act(() => {if (boundary === 'catalogue before') invalidate(); select({target: {value: 'other'}});});
  expect(confirm).toHaveBeenCalledTimes(boundary === 'catalogue before' ? 0 : 1);
  if (boundary === 'current') await waitFor(() => expect(controller.getSnapshot().loadedDocumentId).toBe('other'));
  else {
    expect(controller.getSnapshot().documentId).toBe('fixture');
    expect(controller.getSnapshot().draft).toBe(positionCandidate);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/documents/other'))).toHaveLength(0);
  }
});
it('keeps automatic opt-out usable while current validation is pending and blocks fresh manual renders', async () => {
  const base = positionServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...await (await base.fetcher(url, init)).json(), capabilities: { snapshots: true } });
    return base.fetcher(url, init);
  });
  mountPersistentEditor(fetcher, { layout: 'v7' });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Render snapshots' })).toBeEnabled());
  const consent = screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' });
  fireEvent.click(consent);
  expect(consent).toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: 'Validate schema' }));
  await waitFor(() => expect(base.releases).toHaveLength(1));
  fireEvent.click(consent);
  expect(consent).not.toBeChecked();
  expect(screen.getByRole('button', { name: 'Render snapshots' })).toBeDisabled();
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(0);
});
it.each(['Scene camera', 'Image resolution', 'Camera for desk', 'Preview mode', 'draft'])(
  'retires snapshot authority through the existing synchronous Editor %s epoch (same-turn ABA)', async label => {
    const base = positionServer();
    const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/editor') return response({ ...await (await base.fetcher(url, init)).json(), capabilities: { snapshots: true } });
      return base.fetcher(url, init);
    });
    mountPersistentEditor(fetcher, { layout: 'v7' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Render snapshots' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Collapse generation' }));
    const button = screen.getByRole('button', { name: 'Render snapshots' });
    const props = Object.keys(button).find(key => key.startsWith('__reactProps$'))!;
    const click = (button as unknown as Record<string, { onClick: () => void }>)[props].onClick;
    fetcher.mockClear();
    if (label === 'draft') {
      const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
      act(() => {
        cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: positionSource + '# B' } });
        cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: positionSource } });
        click();
      });
    } else {
      const node = screen.getByLabelText(label) as HTMLSelectElement;
      const original = node.value;
      const other = Array.from(node.options).find(option => option.value && option.value !== original)!;
      const change = retainedChange(node);
      act(() => { change({ target: { value: other.value } }); change({ target: { value: original } }); click(); });
    }
    await act(async () => {});
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/session/activity') || url.endsWith('/editor/snapshots'))).toHaveLength(0);
  },
);
it.each(['Document', 'Scene camera', 'Image resolution', 'Camera for desk', 'Preview mode'])('retires Editor authority synchronously before %s commits, including A→B→A', async label => {
  const {fetcher} = positionServer();
  const inspector = vi.fn((_props: Parameters<NonNullable<EditorViewProps['renderInspector']>>[0]) => null);
  mountPersistentEditor(fetcher, {layout: 'v7', renderInspector: inspector});
  await waitFor(() => expect(inspector.mock.calls.at(-1)?.[0].validation?.valid).toBe(true));
  // Capture a committed control after the load effect's no-op checking update.
  fireEvent.click(screen.getByRole('button', {name: 'Collapse generation'}));
  const old = inspector.mock.calls.at(-1)![0].editing!;
  expect(old.isCurrent()).toBe(true);
  const node = screen.getByLabelText(label) as HTMLSelectElement;
  const original = node.value;
  const other = Array.from(node.options).find(option => option.value && option.value !== original)!;
  const change = retainedChange(node);
  act(() => {
    change({target: {value: other.value}});
    change({target: {value: original}});
    expect(old.isCurrent()).toBe(false);
    expect(old.onApply(positionCandidate)).toBe(false);
  });
  expect(CodeMirrorView.findFromDOM(screen.getByRole('textbox', {name: 'YAML editor'}))!.state.doc.toString()).toBe(positionSource);
});
it.each(['Restore draft', 'Apply generated YAML'])('retires position authority before %s replaces source bytes', async action => {
  const base = positionServer();
  const next = positionSource + '# replacement\n';
  if (action === 'Restore draft') sessionStorage.setItem('arena.editor.draft.v1', JSON.stringify({version: 1, documentId: 'fixture', viewId: 'frozen-position', sourceHash: positionHash(positionSource), draft: next, prompt: ''}));
  const generatedJob = {
    id: 'generated-position', workspace_id: 'default', kind: 'generate', status: 'succeeded', stage: 'complete',
    created_at: 0, updated_at: 0, created_by_session_id: 's', error: null,
    inputs: {operation: 'refine', document_id: 'frozen-position', input_hash: positionHash(positionSource), base_yaml: positionSource},
    result: {yaml_text: next, validation: positionProjection(next)},
  };
  if (action === 'Apply generated YAML') sessionStorage.setItem('arena:editor:generate:v1', JSON.stringify({payload: {...generatedJob.inputs, idempotency_key: 'retained'}, job: generatedJob}));
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (action === 'Apply generated YAML' && url.endsWith('/workspaces/default')) return response({id: 'default', name: 'Arena', event_cursor: 0, jobs: [generatedJob]});
    if (url.endsWith('/jobs/generated-position')) return response(generatedJob);
    return base.fetcher(url, init);
  });
  const inspector = vi.fn((_props: Parameters<NonNullable<EditorViewProps['renderInspector']>>[0]) => null);
  mountPersistentEditor(fetcher, {layout: 'v7', renderInspector: inspector});
  const button = await screen.findByRole('button', {name: action});
  await waitFor(() => expect(inspector.mock.calls.at(-1)?.[0].validation?.valid).toBe(true));
  fireEvent.click(screen.getByRole('button', {name: 'Collapse inspector'}));
  const old = inspector.mock.calls.at(-1)![0].editing!;
  expect(old.isCurrent()).toBe(true);
  const key = Object.keys(button).find(key => key.startsWith('__reactProps$'))!;
  const replace = (button as unknown as Record<string, {onClick: () => void}>)[key].onClick;
  act(() => { replace(); expect(old.isCurrent()).toBe(false); expect(old.onApply(positionCandidate)).toBe(false); });
  expect(CodeMirrorView.findFromDOM(screen.getByRole('textbox', {name: 'YAML editor'}))!.state.doc.toString()).toBe(next);
});
it.each(['same-turn draft ABA', 'same-turn validation', 'same-turn options ABA', 'same-turn document', 'session before render', 'active ABA', 'options ABA', 'unmount', 'backup replacement'] as const)('retires captured Editor apply callbacks after %s', async gate => {
  const {fetcher} = positionServer();
  const inspector = vi.fn((_props: Parameters<NonNullable<EditorViewProps['renderInspector']>>[0]) => null);
  const props = {layout: 'v7' as const, renderInspector: inspector};
  const view = mountPersistentEditor(fetcher, props);
  await waitFor(() => expect(inspector.mock.calls.at(-1)?.[0].validation?.valid).toBe(true));
  // Capture a committed control after the load effect's no-op checking update.
  fireEvent.click(screen.getByRole('button', {name: 'Collapse generation'}));
  const old = inspector.mock.calls.at(-1)![0].editing!;
  expect(old.isCurrent()).toBe(true);
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', {name: 'YAML editor'}))!;
  let applied: boolean | undefined;
  if (gate === 'same-turn draft ABA') act(() => {
    cm.dispatch({changes: {from: 0, to: cm.state.doc.length, insert: positionSource + '# B'}});
    cm.dispatch({changes: {from: 0, to: cm.state.doc.length, insert: positionSource}});
    applied = old.onApply(positionCandidate);
  });
  else if (gate === 'same-turn validation') act(() => {
    fireEvent.click(screen.getByRole('button', {name: 'Validate schema'}));
    applied = old.onApply(positionCandidate);
  });
  else if (gate === 'same-turn options ABA') act(() => {
    fireEvent.change(screen.getByLabelText('Scene camera'), {target: {value: 'top'}});
    fireEvent.change(screen.getByLabelText('Scene camera'), {target: {value: 'isometric'}});
    applied = old.onApply(positionCandidate);
  });
  else if (gate === 'same-turn document') act(() => {
    fireEvent.change(screen.getByLabelText('Document'), {target: {value: 'other'}});
    applied = old.onApply(positionCandidate);
  });
  else {
    if (gate === 'session before render') view.api.session = {...view.api.session!};
    if (gate === 'active ABA') {view.setProps({...props, active: false}); view.setProps(props);}
    if (gate === 'options ABA') {
      fireEvent.change(screen.getByLabelText('Scene camera'), {target: {value: 'top'}});
      fireEvent.change(screen.getByLabelText('Scene camera'), {target: {value: 'isometric'}});
    }
    if (gate === 'unmount') view.unmount();
    if (gate === 'backup replacement') sessionStorage.setItem('arena.editor.draft.v1', JSON.stringify({version: 1, documentId: 'fixture', viewId: 'frozen-position', sourceHash: positionHash(positionSource), draft: 'sibling', prompt: ''}));
    act(() => {applied = old.onApply(positionCandidate);});
  }
  expect(applied).toBe(false);
  if (gate !== 'unmount') expect(cm.state.doc.toString()).toBe(positionSource);
});
it('wires V7 root proposal into the persistent raw draft only after exact review, then freshly validates the applied bytes', async () => {
  vi.stubGlobal('crypto', webcrypto);
  const {fetcher, releases} = positionServer();
  const inspector = vi.fn((props: Parameters<NonNullable<EditorViewProps['renderInspector']>>[0]) => <AuthoredInspector {...props} />);
  const view = mountPersistentEditor(fetcher, {layout: 'v7', renderInspector: inspector});
  await screen.findByRole('combobox', {name: 'Authored asset'});
  const yaml = screen.getByRole('textbox', {name: 'YAML editor'}); const cm = CodeMirrorView.findFromDOM(yaml)!;
  fireEvent.change(screen.getByRole('combobox', {name: 'Authored asset'}), {target: {value: 'desk'}});
  fireEvent.change(screen.getByLabelText('Proposed coordinate (m)'), {target: {value: '1.25'}});
  fireEvent.click(screen.getByRole('button', {name: 'Validate position proposal'}));
  await waitFor(() => expect(releases).toHaveLength(1));
  expect(cm.state.doc.toString()).toBe(positionSource);
  expect(inspector.mock.calls.at(-1)![0].validation?.source_hash).toBe(positionHash(positionSource));
  await act(async () => releases[0](response(positionProjection(positionCandidate))));
  expect(cm.state.doc.toString()).toBe(positionSource);
  fireEvent.click(screen.getByRole('checkbox', {name: 'I reviewed this exact source diff'}));
  fireEvent.click(screen.getByRole('button', {name: 'Apply reviewed position'}));
  expect(cm.state.doc.toString()).toBe(positionCandidate);
  expect(inspector.mock.calls.at(-1)![0].validation).toBeNull();
  await waitFor(() => expect(releases).toHaveLength(2));
  const posts = fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate'));
  expect(posts.map(([, init]) => JSON.parse(String(init?.body)))).toEqual([
    {yaml_text: positionCandidate, document_id: 'frozen-position'}, {yaml_text: positionCandidate, document_id: 'frozen-position'},
  ]);
  await act(async () => releases[1](response(positionProjection(positionCandidate))));
  await waitFor(() => expect(inspector.mock.calls.at(-1)![0].validation?.source_hash).toBe(positionHash(positionCandidate)));
  expect(CodeMirrorView.findFromDOM(yaml)).toBe(cm);
  expect(screen.getByRole('button', {name: 'Download current YAML'})).toBeEnabled();
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$|\/jobs$/.test(url))).toHaveLength(0);
  view.unmount();
});

it.each([false, true])('actual App preserves raw download bytes and existing automatic-preview consent=%s through reviewed Apply', async automatic => {
  vi.stubGlobal('crypto', webcrypto);
  const base = positionServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({...await (await base.fetcher(url, init)).json(), capabilities: {snapshots: true}});
    if (url.includes('/editor/previews/')) {
      const hash = url.split('/editor/previews/')[1].split('?')[0];
      return response(hash === validation.canonical_hash ? {status: 'hit', canonical_hash: hash, receipt: {
        canonical_hash: hash, cache_key: 'old-review', options: {view: 'isometric', resolution: 1024, asset_views: {}},
        input_hash: 'old-input', warnings: ['Old render diagnostic retained'], assets: [], scene: {artifact_id: 'old-scene', url: '/api/editor/artifacts/old-scene'},
      }} : {status: 'miss', canonical_hash: hash, receipt: null});
    }
    return base.fetcher(url, init);
  });
  const view = mountEditor(fetcher, '/?layout=v7');
  await screen.findByRole('combobox', {name: 'Authored asset'});
  const yaml = screen.getByRole('textbox', {name: 'YAML editor'});
  const cm = CodeMirrorView.findFromDOM(yaml)!;
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), {target: {value: 'Keep my prompt'}});
  fireEvent.change(screen.getByLabelText('Preview mode'), {target: {value: 'scene'}});
  await screen.findAllByText('Old render diagnostic retained');
  const consent = screen.getByRole('checkbox', {name: 'Automatic previews (GPU jobs)'});
  if (automatic) fireEvent.click(consent);
  fireEvent.change(screen.getByLabelText('Authored asset'), {target: {value: 'desk'}});
  fireEvent.change(screen.getByLabelText('Proposed coordinate (m)'), {target: {value: '1.25'}});
  fireEvent.click(screen.getByRole('button', {name: 'Validate position proposal'}));
  await waitFor(() => expect(base.releases).toHaveLength(1));
  const checked = {...positionProjection(positionCandidate), canonical_hash: 'b'.repeat(64)};
  await act(async () => base.releases[0](response(checked)));
  expect(screen.getByText(/Existing automatic-preview consent is unchanged/)).toHaveTextContent('after fresh validation');
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(0);
  fireEvent.click(screen.getByRole('checkbox', {name: 'I reviewed this exact source diff'}));
  fireEvent.click(screen.getByRole('button', {name: 'Apply reviewed position'}));
  expect(cm.state.doc.toString()).toBe(positionCandidate);
  expect(screen.getByText('Stale · draft changed since this render')).toBeInTheDocument();
  expect(screen.getAllByText('Old render diagnostic retained').length).toBeGreaterThan(0);
  expect(consent).toHaveProperty('checked', automatic);
  const blobs: Blob[] = [];
  vi.spyOn(URL, 'createObjectURL').mockImplementation(blob => {blobs.push(blob as Blob); return 'blob:raw-draft';});
  const clicked = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  fireEvent.click(screen.getByRole('button', {name: 'Download current YAML'}));
  expect(blobs).toHaveLength(1);
  const bytes = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(reader.result as ArrayBuffer); reader.onerror = reject; reader.readAsArrayBuffer(blobs[0]);
  });
  expect(Array.from(new Uint8Array(bytes))).toEqual(Array.from(new TextEncoder().encode(positionCandidate)));
  expect(clicked.mock.instances[0]).toHaveProperty('download', 'arena-draft.yaml');
  await waitFor(() => expect(base.releases).toHaveLength(2));
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate')).map(([, init]) => JSON.parse(String(init?.body)))).toEqual([
    {yaml_text: positionCandidate, document_id: 'frozen-position'}, {yaml_text: positionCandidate, document_id: 'frozen-position'},
  ]);
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(0);
  await act(async () => base.releases[1](response(checked)));
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 1800)); });
  const jobs = fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'));
  expect(jobs).toHaveLength(automatic ? 1 : 0);
  if (automatic) expect(JSON.parse(String(jobs[0][1]?.body))).toMatchObject({yaml_text: positionCandidate, document_id: 'frozen-position'});
  expect(screen.getByRole('textbox', {name: 'YAML editor'})).toBe(yaml);
  expect(CodeMirrorView.findFromDOM(yaml)).toBe(cm);
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('Keep my prompt');
  expect(fetcher.mock.calls.filter(([url]) => /generate|\/save$|\/jobs$/.test(url))).toHaveLength(0);
  view.unmount();
});
function mountPersistentEditor(fetcher = editorServer(), initial: EditorViewProps = {}) {
  const api = new ApiClient(fetcher as typeof fetch);
  let runtimeApi = api;
  let editorMounted = true;
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const router = createRouter({ routeTree: createRootRoute(), history: createMemoryHistory() });
  const tree = (props: EditorViewProps) => <RouterContextProvider router={router}><QueryClientProvider client={cache}><ThemeProvider><RuntimeProvider api={runtimeApi} makePort={noPort}>
    {editorMounted && <EditorView {...props} />}
  </RuntimeProvider></ThemeProvider></QueryClientProvider></RouterContextProvider>;
  const view = render(tree(initial));
  return { ...view, api, cache, setProps: (props: EditorViewProps) => view.rerender(tree(props)),
    setEditorMounted: (mounted: boolean) => { editorMounted = mounted; view.rerender(tree(initial)); },
    setApi: (client: ApiClient) => { runtimeApi = client; view.rerender(tree(initial)); } };
}

it('keeps one real YAML and snapshot surface across V7 collapse, expansion and legacy fallback', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { generation_modes: true } });
    if (url.includes('/editor/previews/')) return response({ status: 'hit', canonical_hash: validation.canonical_hash, receipt: {
      canonical_hash: validation.canonical_hash, cache_key: 'actual-catalogue', options: { view: 'isometric', resolution: 1024, asset_views: {} },
      input_hash: 'hash', warnings: [], assets: [{ id: 'table', artifact_id: 'actual-table', url: '/api/editor/artifacts/actual-table' }], scene: null,
    } });
    return base(url, init);
  });
  const inspector = vi.fn(({ validation: value, onFocusSpecification }: Parameters<NonNullable<EditorViewProps['renderInspector']>>[0]) =>
    <div><span>{value?.spec?.env_name as string}</span><button onClick={onFocusSpecification}>Focus specification</button></div>);
  const view = mountPersistentEditor(fetcher, { layout: 'v7', renderInspector: inspector });
  const image = await screen.findByRole('img', { name: 'table snapshot' });
  const yaml = screen.getByRole('textbox', { name: 'YAML editor' });
  const cm = CodeMirrorView.findFromDOM(yaml)!;
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Retained prompt' } });
  fireEvent.change(screen.getByLabelText('Retrieval policy'), { target: { value: 'require_service' } });
  fireEvent.click(screen.getByLabelText('Refine current environment'));
  fireEvent.click(screen.getByRole('button', { name: 'Collapse generation' }));
  fireEvent.click(screen.getByRole('button', { name: 'Collapse specification' }));
  expect(yaml).not.toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Expand viewport' }));
  expect(image).toBeVisible();
  expect(screen.getByRole('img', { name: 'table snapshot' })).toBe(image);
  fireEvent.click(screen.getByRole('button', { name: 'Restore panels' }));
  fireEvent.click(screen.getByRole('button', { name: 'Focus specification' }));
  await waitFor(() => expect(yaml).toHaveFocus());
  view.setProps({ layout: 'legacy', renderInspector: inspector });
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toBe(yaml);
  expect(CodeMirrorView.findFromDOM(yaml)).toBe(cm);
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('Retained prompt');
  expect(screen.getByLabelText('Refine current environment')).toBeChecked();
  fireEvent.click(screen.getByLabelText('New environment from prompt'));
  expect(screen.getByLabelText('Retrieval policy')).toHaveValue('require_service');
  view.setProps({ layout: 'v7', renderInspector: inspector });
  expect(screen.getByRole('button', { name: 'Expand generation' })).toBeInTheDocument();
  expect(screen.getByRole('img', { name: 'table snapshot' })).toBe(image);
  expect(inspector.mock.calls.at(-1)?.[0].validation).toEqual(validation);
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});
const validation = {
  valid: true,
  source_hash: 'hash',
  canonical_hash: 'a'.repeat(64),
  errors: [],
  warnings: [],
  spec: { env_name: 'real_document' },
  summary: 'One authored object',
  graph: {
    nodes: [
      { id: 'table', label: 'Table', role: 'object', properties: { registry_name: 'table' } },
      { id: 'relation', label: 'Explicit relation', role: 'reifier', properties: {} },
    ],
    edges: [],
  },
  assets: [{ id: 'table', role: 'object', properties: {} }],
  relations: [{ kind: 'is_anchor', subject: 'table', reference: null }],
  reified_relations: [],
  tasks: [{ kind: 'Pick', description: 'Pick an object' }],
};
it('retires inactive authoring reads, validation, media and credential entry without losing controls', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { generation_modes: true, snapshots: true } });
    if (url === '/api/model-settings') return response({ providers: PROVIDERS, configured: false, source: 'none', provider: null, model: null,
      credential_ref: null, expires_at: null, session_keys_allowed: true });
    if (url.includes('/editor/previews/')) return response({ status: 'miss', canonical_hash: validation.canonical_hash, receipt: null });
    return base(url, init);
  });
  const view = mountPersistentEditor(fetcher, { layout: 'v7', active: false });
  await waitFor(() => expect(view.api.session).not.toBeNull());
  expect(fetcher.mock.calls.filter(([url]) => /\/editor(?:$|\/)|\/model-settings$/.test(url))).toHaveLength(0);
  view.setProps({ layout: 'v7', active: true });
  await screen.findByRole('button', { name: 'Inspect Table' });
  const yaml = screen.getByRole('textbox', { name: 'YAML editor' });
  const cm = CodeMirrorView.findFromDOM(yaml)!;
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Keep prompt' } });
  fireEvent.click(screen.getByLabelText('Refine current environment'));
  fireEvent.change(screen.getByLabelText('Scene camera'), { target: { value: 'top' } });
  fireEvent.change(screen.getByLabelText('Image resolution'), { target: { value: '512' } });
  fireEvent.change(screen.getByLabelText('Camera for table'), { target: { value: 'front' } });
  fireEvent.click(screen.getByRole('checkbox', { name: /I consent/ }));
  const password = screen.getByLabelText('API key');
  fireEvent.change(password, { target: { value: 'dummy-inactive-secret' } });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' }));
  act(() => cm.dispatch({ changes: { from: cm.state.doc.length, insert: '\n# retained inactive edit' } }));
  view.setProps({ layout: 'v7', active: false });
  expect(view.container.querySelector('#workspace')).toBeNull();
  expect(yaml).not.toBeVisible();
  expect(password).not.toBeInTheDocument();
  expect(password).toHaveValue('');
  expect(view.container.querySelector('img')).toBeNull();
  expect(view.container.querySelector('[data-node="table"]')).toBeNull();
  const reads = fetcher.mock.calls.filter(([url]) => /\/editor(?:$|\/)/.test(url)).length;
  await act(async () => { await view.cache.invalidateQueries({ queryKey: ['preview-catalogue'] }); await new Promise(resolve => setTimeout(resolve, 1800)); });
  expect(fetcher.mock.calls.filter(([url]) => /\/editor(?:$|\/)/.test(url))).toHaveLength(reads);
  view.setProps({ layout: 'legacy', active: true });
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toBe(yaml);
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('Keep prompt');
  expect(screen.getByLabelText('Refine current environment')).toBeChecked();
  expect(screen.getByLabelText('Scene camera')).toHaveValue('top');
  expect(screen.getByLabelText('Image resolution')).toHaveValue('512');
  expect(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' })).not.toBeChecked();
  expect(screen.getByLabelText('API key')).toHaveValue('');
  await screen.findByRole('button', { name: 'Inspect Table' });
  expect(screen.getByLabelText('Camera for table')).toHaveValue('front');
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});

it('retires inspector bindings and manual validation callbacks across inactive and A-to-B-to-A drafts', async () => {
  const base = editorServer();
  let release: ((value: Response) => void) | undefined;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/editor/validate')) return new Promise<Response>(resolve => { release = resolve; });
    return base(url, init);
  });
  const inspector = vi.fn((props: Parameters<NonNullable<EditorViewProps['renderInspector']>>[0]) =>
    <button onClick={props.onFocusSpecification}>Focus specification</button>);
  const props = { layout: 'v7' as const, renderInspector: inspector };
  const view = mountPersistentEditor(fetcher, props);
  await screen.findByRole('button', { name: 'Inspect Table' });
  const yaml = screen.getByRole('textbox', { name: 'YAML editor' });
  const cm = CodeMirrorView.findFromDOM(yaml)!;
  const original = cm.state.doc.toString();
  const oldBinding = inspector.mock.calls.at(-1)![0];
  act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: B' } }));
  act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: original } }));
  expect(inspector.mock.calls.at(-1)![0].bindingKey).not.toBe(oldBinding.bindingKey);
  fireEvent.click(screen.getByRole('button', { name: 'Collapse specification' }));
  act(() => oldBinding.onFocusSpecification());
  expect(yaml).not.toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Expand specification' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Validate schema' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Validate schema' }));
  await waitFor(() => expect(release).toBeDefined());
  view.setProps({ ...props, active: false });
  expect(inspector.mock.calls.at(-1)![0].validation).toBeNull();
  view.setProps({ ...props, active: true });
  await act(async () => { release!(response({ ...validation, valid: false, errors: ['obsolete validation'], summary: 'obsolete validation' })); });
  expect(screen.queryByText('obsolete validation')).not.toBeInTheDocument();
  expect(screen.getByText('Schema valid')).toBeInTheDocument();
  expect(inspector.mock.calls.at(-1)![0].bindingKey).not.toBe(oldBinding.bindingKey);
});

it('withholds a reused-session projection immediately and revalidates the retained frozen source', async () => {
  const base = editorServer();
  let release: ((value: Response) => void) | undefined;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { snapshots: true } });
    if (url.endsWith('/editor/validate')) return new Promise<Response>(resolve => { release = resolve; });
    return base(url, init);
  });
  const inspector = vi.fn((_props: Parameters<NonNullable<EditorViewProps['renderInspector']>>[0]) => null);
  const props = { layout: 'v7' as const, renderInspector: inspector };
  const view = mountPersistentEditor(fetcher, props);
  await screen.findByRole('button', { name: 'Inspect Table' });
  const yaml = screen.getByRole('textbox', { name: 'YAML editor' });
  const cm = CodeMirrorView.findFromDOM(yaml)!;
  const before = inspector.mock.calls.at(-1)![0];
  view.api.session = { ...view.api.session! };
  view.setProps(props);
  expect(inspector.mock.calls.at(-1)![0].validation).toBeNull();
  expect(inspector.mock.calls.at(-1)![0].bindingKey).not.toBe(before.bindingKey);
  expect(screen.getByRole('button', { name: 'Save revision' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Render snapshots' })).toBeDisabled();
  expect(screen.queryByRole('button', { name: 'Inspect Table' })).not.toBeInTheDocument();
  await waitFor(() => expect(release).toBeDefined());
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(1);
  expect(JSON.parse(String(fetcher.mock.calls.find(([url]) => url.endsWith('/editor/validate'))![1]?.body)))
    .toEqual({ yaml_text: 'env_name: real_document', document_id: 'frozen-fixture' });
  await act(async () => release!(response(validation)));
  await screen.findByRole('button', { name: 'Inspect Table' });
  expect(inspector.mock.calls.at(-1)![0].validation).toEqual(validation);
  expect(CodeMirrorView.findFromDOM(yaml)).toBe(cm);
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});

it.each(['before', 'after'] as const)('rejects retired validation success/error %s replacement rerender', async timing => {
  const base = editorServer();
  const releases: ((value: Response) => void)[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/editor/validate')) return new Promise<Response>(resolve => { releases.push(resolve); });
    return base(url, init);
  });
  const view = mountPersistentEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  for (const status of [200, 503]) {
    fireEvent.click(screen.getByRole('button', { name: 'Validate schema' }));
    await waitFor(() => expect(releases.length).toBeGreaterThan(0));
    const retained = view.cache.getQueryData<{ validation: unknown }>(['editor-draft'])!.validation;
    view.api.session = { ...view.api.session! };
    if (timing === 'after') view.setProps({});
    await act(async () => releases.shift()!(response(status === 200
      ? { ...validation, summary: 'retired success' } : { detail: 'retired error' }, status)));
    expect(view.cache.getQueryData<{ validation: unknown }>(['editor-draft'])!.validation).toBe(retained);
    expect(screen.queryByText('retired error')).not.toBeInTheDocument();
    view.setProps({});
    await waitFor(() => expect(releases.length).toBe(1));
    await act(async () => releases.shift()!(response(validation)));
    await screen.findByRole('button', { name: 'Inspect Table' });
  }
});

it('rejects retained inspector focus and manual validate before replacement rerender', async () => {
  const fetcher = editorServer();
  const inspector = vi.fn((_props: Parameters<NonNullable<EditorViewProps['renderInspector']>>[0]) => null);
  const view = mountPersistentEditor(fetcher, { layout: 'v7', renderInspector: inspector });
  await screen.findByRole('button', { name: 'Inspect Table' });
  const yaml = screen.getByRole('textbox', { name: 'YAML editor' });
  const oldBinding = inspector.mock.calls.at(-1)![0];
  fireEvent.click(screen.getByRole('button', { name: 'Collapse specification' }));
  view.api.session = { ...view.api.session! };
  act(() => oldBinding.onFocusSpecification());
  expect(yaml).not.toBeVisible();
  // A retained DOM handler must not dispatch against the replacement session either.
  fireEvent.click(screen.getByRole('button', { name: 'Validate schema', hidden: true }));
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate'))).toHaveLength(0);
});

it.each([
  ['before', 200], ['before', 503], ['after', 200], ['after', 503],
] as const)('rejects a retired source load %s replacement rerender (HTTP %s)', async (timing, status) => {
  const base = editorServer();
  const releases: ((value: Response) => void)[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/editor/documents/')) return new Promise<Response>(resolve => { releases.push(resolve); });
    return base(url, init);
  });
  const view = mountPersistentEditor(fetcher);
  await waitFor(() => expect(releases).toHaveLength(1));
  view.api.session = { ...view.api.session! };
  if (timing === 'after') view.setProps({});
  await act(async () => releases.shift()!(status === 200
    ? response({ ...(await (await base('/api/editor/documents/fixture')).json()), yaml_text: 'env_name: retired_source' })
    : response({ detail: 'retired load error' }, status)));
  expect(view.cache.getQueryData<{ draft: string }>(['editor-draft'])!.draft).toBe('');
  expect(screen.queryByText('retired load error')).not.toBeInTheDocument();
  view.setProps({});
  await waitFor(() => expect(releases, JSON.stringify({ cached: view.cache.getQueryData(['editor-draft']),
    generation: view.api.sessionGeneration, session: view.api.session?.session_id, calls: fetcher.mock.calls.map(([url]) => url),
    status: view.container.querySelector('.document-bar')?.textContent })).toHaveLength(1));
  expect(screen.getByRole('combobox', { name: 'Document' })).toBeDisabled();
  await act(async () => releases.shift()!(await base('/api/editor/documents/fixture')));
  await screen.findByRole('button', { name: 'Inspect Table' });
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('env_name: real_document');
  expect(screen.getByRole('combobox', { name: 'Document' })).toBeEnabled();
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(2);
});

it('withholds validation when the ApiClient changes even with identical session ID and generation', async () => {
  const base = editorServer();
  let releaseOld: ((value: Response) => void) | undefined;
  const oldFetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/editor/validate')) return new Promise<Response>(resolve => { releaseOld = resolve; });
    return base(url, init);
  });
  const inspector = vi.fn((_props: Parameters<NonNullable<EditorViewProps['renderInspector']>>[0]) => null);
  const view = mountPersistentEditor(oldFetcher, { layout: 'v7', renderInspector: inspector });
  await screen.findByRole('button', { name: 'Inspect Table' });
  const yaml = screen.getByRole('textbox', { name: 'YAML editor' });
  const oldBinding = inspector.mock.calls.at(-1)![0];
  fireEvent.click(screen.getByRole('button', { name: 'Validate schema' }));
  await waitFor(() => expect(releaseOld).toBeDefined());
  const releases: ((value: Response) => void)[] = [];
  const replacementFetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/editor/validate')) return new Promise<Response>(resolve => { releases.push(resolve); });
    return base(url, init);
  });
  const replacement = new ApiClient(replacementFetcher as typeof fetch);
  await replacement.connect();
  expect(replacement.sessionGeneration).toBe(view.api.sessionGeneration);
  view.setApi(replacement);
  expect(inspector.mock.calls.at(-1)![0].validation).toBeNull();
  expect(inspector.mock.calls.at(-1)![0].bindingKey).not.toBe(oldBinding.bindingKey);
  expect(screen.getByRole('button', { name: 'Save revision' })).toBeDisabled();
  await act(async () => releaseOld!(response({ ...validation, summary: 'retired client result' })));
  expect(JSON.stringify(view.cache.getQueryData(['editor-draft']))).not.toContain('retired client result');
  await waitFor(() => expect(releases).toHaveLength(1));
  expect(replacementFetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(0);
  expect(JSON.parse(String(replacementFetcher.mock.calls.find(([url]) => url.endsWith('/editor/validate'))![1]?.body)))
    .toEqual({ yaml_text: 'env_name: real_document', document_id: 'frozen-fixture' });
  await act(async () => releases.shift()!(response(validation)));
  await screen.findByRole('button', { name: 'Inspect Table' });
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toBe(yaml);
});

it('preserves source and validation ownership through ordinary activity deadline extension', async () => {
  const base = editorServer();
  const loads: ((value: Response) => void)[] = [];
  const validations: ((value: Response) => void)[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/editor/documents/')) return new Promise<Response>(resolve => loads.push(resolve));
    if (url.endsWith('/editor/validate')) return new Promise<Response>(resolve => validations.push(resolve));
    if (url.endsWith('/session/activity')) return response({ session_id: 's', csrf_token: 'csrf', expires_at: 99999999999 });
    return base(url, init);
  });
  const inspector = vi.fn((_props: Parameters<NonNullable<EditorViewProps['renderInspector']>>[0]) => null);
  const props = { layout: 'v7' as const, renderInspector: inspector };
  const view = mountPersistentEditor(fetcher, props);
  await waitFor(() => expect(loads).toHaveLength(1));
  const generation = view.api.sessionGeneration;
  const originalSession = view.api.session;
  await act(async () => { await view.api.activity(); });
  expect(view.api.session).not.toBe(originalSession);
  expect(view.api.sessionGeneration).toBe(generation);
  view.setProps(props);
  await act(async () => loads.shift()!(await base('/api/editor/documents/fixture')));
  await screen.findByRole('button', { name: 'Inspect Table' });
  const binding = inspector.mock.calls.at(-1)![0];
  const retained = view.cache.getQueryData<{ validation: unknown }>(['editor-draft'])!.validation;
  fireEvent.click(screen.getByRole('button', { name: 'Validate schema' }));
  await waitFor(() => expect(validations).toHaveLength(1));
  await act(async () => { await view.api.activity(); });
  view.setProps({ ...props, layout: 'legacy' });
  expect(inspector.mock.calls.at(-1)![0].bindingKey).toBe(binding.bindingKey);
  expect(inspector.mock.calls.at(-1)![0].validation).toEqual(validation);
  expect(view.cache.getQueryData<{ validation: unknown }>(['editor-draft'])!.validation).toBe(retained);
  await act(async () => validations.shift()!(response({ ...validation, summary: 'current activity result' })));
  await screen.findAllByText('current activity result');
  view.setProps({ ...props, active: false });
  expect(inspector.mock.calls.at(-1)![0].validation).toBeNull();
  view.setProps(props);
  expect(inspector.mock.calls.at(-1)![0].validation?.summary).toBe('current activity result');
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate'))).toHaveLength(1);
});

it('retains cached controller validation on same-client remount but revalidates a replacement generation', async () => {
  const fetcher = editorServer();
  const inspector = vi.fn((_props: Parameters<NonNullable<EditorViewProps['renderInspector']>>[0]) => null);
  const view = mountPersistentEditor(fetcher, { layout: 'legacy', renderInspector: inspector });
  await screen.findByRole('button', { name: 'Inspect Table' });
  const retained = view.cache.getQueryData<{ validation: unknown }>(['editor-draft'])!.validation;
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'cached prompt' } });
  view.setEditorMounted(false);
  view.setEditorMounted(true);
  expect(inspector.mock.calls.at(-1)![0].validation).toEqual(validation);
  expect(view.cache.getQueryData<{ validation: unknown }>(['editor-draft'])!.validation).toBe(retained);
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('cached prompt');
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate'))).toHaveLength(0);
  view.setEditorMounted(false);
  view.api.session = { ...view.api.session! };
  view.setEditorMounted(true);
  expect(inspector.mock.calls.at(-1)![0].validation).toBeNull();
  await screen.findByRole('button', { name: 'Inspect Table' });
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate'))).toHaveLength(1);
});

it.each(['session', 'client'] as const)('retires automatic authority on same-ID %s replacement without retiring an accepted job or draft', async mode => {
  const base = editorServer();
  const job = { id: 'accepted-auto', kind: 'snapshots', workspace_id: 'default', status: 'running', stage: 'accepted render is observed',
    inputs: {}, result: null, error: null, created_at: 0, updated_at: 0, created_by_session_id: 's' };
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { snapshots: true } });
    if (url.endsWith('/editor/snapshots')) return response(job);
    if (url.endsWith('/jobs/accepted-auto')) return response(job);
    return base(url, init);
  });
  const view = mountPersistentEditor(fetcher, { layout: 'v7' });
  await screen.findByRole('button', { name: 'Inspect Table' });
  const yaml = screen.getByRole('textbox', { name: 'YAML editor' });
  const cm = CodeMirrorView.findFromDOM(yaml)!;
  act(() => cm.dispatch({ changes: { from: cm.state.doc.length, insert: '\n# retained through authority retirement' } }));
  await screen.findByRole('button', { name: 'Inspect Table' });
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Retain this prompt' } });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' }));
  fireEvent.change(screen.getByLabelText('Scene camera'), { target: { value: 'top' } });
  await screen.findByText('accepted render is observed', {}, { timeout: 4000 });
  await screen.findByText(/1 \/ 3 automatic jobs used this enable/);
  const retained = sessionStorage.getItem('arena:editor:snapshots:v1');
  const validationsBefore = fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate')).length;
  if (mode === 'session') {
    view.api.session = { ...view.api.session! };
    view.setProps({ layout: 'legacy' });
  } else {
    const replacement = new ApiClient(fetcher as typeof fetch);
    await replacement.connect();
    expect(replacement.sessionGeneration).toBe(view.api.sessionGeneration);
    // Keep this case about equal-generation client replacement, not a second
    // session established by RuntimeProvider's connection effect.
    vi.spyOn(replacement, 'connect').mockResolvedValue(replacement.session!);
    view.setApi(replacement);
  }
  expect(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' })).not.toBeChecked();
  expect(screen.getByText(/0 \/ 3 automatic jobs used this enable/)).toBeInTheDocument();
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toBe(yaml);
  expect(CodeMirrorView.findFromDOM(yaml)).toBe(cm);
  expect(cm.state.doc.toString()).toContain('# retained through authority retirement');
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('Retain this prompt');
  expect(sessionStorage.getItem('arena:editor:snapshots:v1')).toBe(retained);
  expect(screen.getByText('accepted render is observed')).toBeInTheDocument();
  const readsBefore = fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/accepted-auto')).length;
  fireEvent.click(screen.getByRole('button', { name: 'Refresh job status' }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/accepted-auto')).length).toBeGreaterThan(readsBefore));
  await screen.findByRole('button', { name: 'Inspect Table' });
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate')).length).toBeGreaterThan(validationsBefore));
  expect(JSON.parse(String(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate')).at(-1)![1]?.body)))
    .toEqual({ yaml_text: cm.state.doc.toString(), document_id: 'frozen-fixture' });
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/cancel'))).toHaveLength(0);
});

it.each(['session', 'client'] as const)('requires fresh editor metadata after same-ID %s replacement and drops the old response', async mode => {
  const base = editorServer();
  const metadata = { ...(await (await base('/api/editor')).json()), capabilities: { snapshots: true, generation_modes: true } };
  let delay = false;
  const releases: ((value: Response) => void)[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return delay
      ? new Promise<Response>(resolve => { releases.push(resolve); }) : response(metadata);
    return base(url, init);
  });
  const view = mountPersistentEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  const yaml = screen.getByRole('textbox', { name: 'YAML editor' });
  const cm = CodeMirrorView.findFromDOM(yaml)!;
  act(() => cm.dispatch({ changes: { from: cm.state.doc.length, insert: '\n# keep draft while metadata is unavailable' } }));
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Keep metadata-independent prompt' } });
  delay = true;
  act(() => { void view.cache.invalidateQueries({ queryKey: ['editor'] }); });
  await waitFor(() => expect(releases).toHaveLength(1));
  if (mode === 'session') {
    view.api.session = { ...view.api.session! };
    view.setProps({});
  } else {
    const replacement = new ApiClient(fetcher as typeof fetch);
    await replacement.connect();
    expect(replacement.sessionGeneration).toBe(view.api.sessionGeneration);
    // Keep this case about equal-generation client replacement, not a second
    // session established by RuntimeProvider's connection effect.
    vi.spyOn(replacement, 'connect').mockResolvedValue(replacement.session!);
    view.setApi(replacement);
  }
  expect(screen.getByRole('combobox', { name: 'Document' })).toBeDisabled();
  expect(screen.queryByLabelText('New environment from prompt')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Render snapshots' })).toBeDisabled();
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toBe(yaml);
  expect(cm.state.doc.toString()).toContain('# keep draft while metadata is unavailable');
  await waitFor(() => expect(releases).toHaveLength(2));
  await act(async () => releases[1](response({ ...metadata, capabilities: { snapshots: false, generation_modes: false },
    limitations: ['Current owner catalogue'] })));
  await screen.findByText('Current owner catalogue');
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Document' })).toBeEnabled());
  await act(async () => releases[0](response({ ...metadata, limitations: ['Retired owner catalogue'] })));
  expect(screen.queryByText('Retired owner catalogue')).not.toBeInTheDocument();
  expect(JSON.stringify(view.cache.getQueriesData({ queryKey: ['editor'] }))).not.toContain('Retired owner catalogue');
  expect(screen.queryByLabelText('New environment from prompt')).not.toBeInTheDocument();
  await screen.findByRole('button', { name: 'Inspect Table' });
  expect(screen.getByRole('button', { name: 'Render snapshots' })).toBeDisabled();
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('Keep metadata-independent prompt');
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(1);
  expect(JSON.parse(String(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate')).at(-1)![1]?.body)))
    .toEqual({ yaml_text: cm.state.doc.toString(), document_id: 'frozen-fixture' });
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});

it.each(['off', 'off-on', 'session-before-render', 'session', 'client', 'unmount'] as const)('does not POST snapshots when automatic authority is retired by %s during activity preflight', async mode => {
  const base = editorServer();
  let release: (() => void) | undefined;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { snapshots: true } });
    if (url.endsWith('/session/activity')) await new Promise<void>(resolve => { release = resolve; });
    return base(url, init);
  });
  const view = mountPersistentEditor(fetcher, { layout: 'v7' });
  await screen.findByRole('button', { name: 'Inspect Table' });
  const consent = screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' });
  fireEvent.click(consent);
  fireEvent.change(screen.getByLabelText('Scene camera'), { target: { value: 'top' } });
  await waitFor(() => expect(release).toBeDefined(), { timeout: 4000 });
  expect(screen.getByRole('button', { name: 'Submitting render…' })).toBeDisabled();
  if (mode === 'off' || mode === 'off-on') {
    fireEvent.click(consent);
    expect(consent).not.toBeChecked();
    if (mode === 'off-on') fireEvent.click(consent);
  } else if (mode === 'session' || mode === 'session-before-render') {
    view.api.session = { ...view.api.session! };
    if (mode === 'session') view.setProps({});
  } else if (mode === 'client') {
    const replacement = new ApiClient(fetcher as typeof fetch);
    await replacement.connect();
    vi.spyOn(replacement, 'connect').mockResolvedValue(replacement.session!);
    view.setApi(replacement);
  } else view.setEditorMounted(false);
  await act(async () => { release!(); });
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Submitting render…' })).not.toBeInTheDocument());
  // Inspect actual transport, not the hook's result: a post-dispatch guard is too late.
  expect(fetcher.mock.calls.filter(([url, init]) => url.endsWith('/editor/snapshots') && init?.method === 'POST')).toHaveLength(0);
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/cancel'))).toHaveLength(0);
});

it('observes a snapshot accepted after automatic opt-out without reusing dispatch consent', async () => {
  const base = editorServer();
  let release: (() => void) | undefined;
  const job = { id: 'accepted-after-optout', kind: 'snapshots', workspace_id: 'default', status: 'running',
    stage: 'Accepted render remains observed', inputs: {}, result: null };
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { snapshots: true } });
    if (url.endsWith('/editor/snapshots')) {
      await new Promise<void>(resolve => { release = resolve; });
      return response(job);
    }
    if (url.endsWith('/jobs/accepted-after-optout')) return response(job);
    return base(url, init);
  });
  mountPersistentEditor(fetcher, { layout: 'v7' });
  await screen.findByRole('button', { name: 'Inspect Table' });
  const consent = screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' });
  fireEvent.click(consent);
  fireEvent.change(screen.getByLabelText('Scene camera'), { target: { value: 'top' } });
  await waitFor(() => expect(release).toBeDefined(), { timeout: 4000 });
  fireEvent.click(consent);
  await act(async () => { release!(); });
  await screen.findByText('Accepted render remains observed');
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith('/jobs/accepted-after-optout'))).toBe(true));
  expect(consent).not.toBeChecked();
  expect(JSON.parse(sessionStorage.getItem('arena:editor:snapshots:v1')!)).toMatchObject({ job: { id: job.id } });
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/cancel'))).toHaveLength(0);
});

it('does not dispatch an automatic render after inactivity interrupts its activity preflight', async () => {
  const base = editorServer();
  let release: (() => void) | undefined;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { snapshots: true } });
    if (url.endsWith('/session/activity')) await new Promise<void>(resolve => { release = resolve; });
    return base(url, init);
  });
  const view = mountPersistentEditor(fetcher, { layout: 'v7' });
  await screen.findByRole('button', { name: 'Inspect Table' });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' }));
  fireEvent.change(screen.getByLabelText('Scene camera'), { target: { value: 'top' } });
  await waitFor(() => expect(release).toBeDefined(), { timeout: 4000 });
  view.setProps({ layout: 'legacy', active: false });
  view.setProps({ layout: 'v7', active: true });
  await act(async () => { release!(); });
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(0);
  expect(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' })).not.toBeChecked();
});

it('observes accepted Refine while inactive and applies only the reviewed source-bound candidate on return', async () => {
  const base = editorServer();
  let release: (() => void) | undefined;
  let payload: Record<string, unknown> = {};
  const job = (status: 'queued' | 'succeeded') => ({ id: 'accepted-refine', kind: 'generate', workspace_id: 'default', status, stage: status,
    inputs: { ...payload, input_hash: 'hash' }, result: status === 'succeeded'
      ? { yaml_text: 'env_name: actual_refined_candidate', validation, warnings: [], publication: 'not_published', traces: [] } : null });
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { generation: true, generation_modes: true } });
    if (url.endsWith('/editor/generate')) {
      payload = JSON.parse(String(init?.body));
      await new Promise<void>(resolve => { release = resolve; });
      return response(job('queued'));
    }
    if (url.endsWith('/jobs/accepted-refine')) return response(job('succeeded'));
    return base(url, init);
  });
  const view = mountPersistentEditor(fetcher, { layout: 'v7' });
  await screen.findByRole('button', { name: 'Inspect Table' });
  fireEvent.change(screen.getByLabelText('Retrieval policy'), { target: { value: 'require_service' } });
  fireEvent.click(screen.getByLabelText('Refine current environment'));
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Refine this exact source' } });
  view.setProps({ layout: 'legacy' });
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  await waitFor(() => expect(release).toBeDefined());
  view.setProps({ layout: 'v7', active: false });
  const catalogueReads = fetcher.mock.calls.filter(([url]) => url.includes('/editor/previews/')).length;
  await act(async () => { release!(); });
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith('/jobs/accepted-refine'))).toBe(true));
  expect(JSON.parse(sessionStorage.getItem('arena:editor:generate:v1')!)).toMatchObject({ job: { id: 'accepted-refine' } });
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/editor/previews/'))).toHaveLength(catalogueReads);
  view.setProps({ layout: 'v7' });
  await screen.findByRole('button', { name: 'Apply generated YAML' });
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('real_document');
  expect(payload).toMatchObject({ operation: 'refine', retrieval_policy: 'allow_fallback', prompt: 'Refine this exact source',
    base_yaml: 'env_name: real_document', document_id: 'frozen-fixture' });
  fireEvent.click(screen.getByRole('button', { name: 'Apply generated YAML' }));
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('actual_refined_candidate');
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith('/editor/validate'))).toBe(true));
  const applied = JSON.parse(String(fetcher.mock.calls.find(([url]) => url.endsWith('/editor/validate'))![1]?.body));
  expect(applied).toEqual({ yaml_text: 'env_name: actual_refined_candidate', document_id: 'frozen-fixture' });
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate'))).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([url]) => /snapshots|\/save$/.test(url))).toHaveLength(0);
});

export function editorServer() {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/health')) return response({ capabilities: { diagnostic: false } });
    if (url.endsWith('/sessions') || url.endsWith('/session/activity'))
      return response({ session_id: 's', csrf_token: 'csrf', expires_at: 9999999999 });
    if (url.endsWith('/workspaces/default'))
      return response({ id: 'default', name: 'Arena', jobs: [], event_cursor: 0 });
    if (url === '/api/editor')
      return response({
        default_document_id: 'fixture',
        documents: [{ id: 'fixture', name: 'Fixture', source: 'tests/fixture.yaml' }],
        capabilities: { generation: false, snapshots: false, neo4j: true },
        limitations: [],
      });
    if (url.includes('/editor/documents/'))
      return response({
        document_id: 'frozen-fixture',
        source: 'tests/fixture.yaml',
        yaml_text: 'env_name: real_document',
        source_hash: 'hash',
        validation,
      });
    if (url.endsWith('/editor/validate'))
      return response(
        JSON.parse(String(init?.body)).yaml_text.includes('broken')
          ? {
              ...validation,
              valid: false,
              errors: ['Invalid environment'],
              graph: { nodes: [], edges: [] },
            }
          : validation,
      );
    if (url.includes('/editor/previews/')) return response({ status: 'miss', canonical_hash: validation.canonical_hash, receipt: null });
    return response({ detail: 'not installed' }, 404);
  });
}
export function mountEditor(fetcher = editorServer(), path = '/') {
  return render(
    <App
      api={new ApiClient(fetcher as typeof fetch)}
      cache={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}
      history={createMemoryHistory({ initialEntries: [path] })}
      makePort={() => null}
    />,
  );
}
it.each([undefined, false, true, 'true'])('passes only explicit publication execution capability through the editor: %s', async capability => {
 const base = editorServer(), res = 'a'.repeat(32), rev = 'b'.repeat(32), digest = 'c'.repeat(64);
 const reservation = { store_id: 'local', registry_id: 'registry', reservation_id: res, revision_id: rev, version: 1, family: 'Example', workflow_id: 'prepared', parent_revision_id: null, source: { job_id: 'd'.repeat(32), attempt_id: 'e'.repeat(32), generation: 1, receipt_sha256: digest, request_sha256: digest }, publication_request: { effect_id: 'effect', target_profile: { profile_id: 'profile', revision: digest, scope_ownership: 'cooperative_immutable' } } };
 const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
  if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { research_versions: true, publication_execution: capability } });
  if (url.endsWith('/research/stores')) return response({ stores: [{ store_id: 'local', available: true }] });
  if (url.includes('/versions?')) return response({ versions: [{ ...reservation, state: 'committed', source_job_id: reservation.source.job_id, manifest_digest: digest, open_source: {kind: 'research_version', id: `research-version:local:${res}:${digest}`} }], latest_version: 1, next_after_version: null });
  if (url.endsWith(`/versions/${res}`)) return response({ reservation, manifest: { digest, binding: reservation }, relative_directory: 'final/Example/v1', publication_intent_id: 'effect' });
  return base(url, init);
 });
 const view = mountEditor(fetcher);
 await screen.findByRole('button', { name: 'Open research versions' });
 await waitFor(() => expect(view.container.querySelector('.cm-content')?.textContent).toContain('real_document'));
 const yaml = view.container.querySelector('.cm-content')?.textContent;
 fireEvent.click(screen.getByRole('button', { name: 'Open research versions' }));
 await screen.findByRole('option', { name: 'local' });
 fireEvent.change(screen.getByLabelText('Research store'), { target: { value: 'local' } });
 fireEvent.change(screen.getByLabelText('Research family'), { target: { value: 'Example' } });
 fireEvent.click(await screen.findByRole('button', { name: 'Select version 1' }));
 await screen.findByRole('link', { name: 'Download verified source' });
 if (capability === true) expect(screen.getByRole('button', { name: 'Open publication execution' })).toBeEnabled();
 else expect(screen.queryByRole('button', { name: 'Open publication execution' })).not.toBeInTheDocument();
 expect(fetcher.mock.calls.some(([u]) => /publication-binding|\/publications\//.test(u))).toBe(false);
 expect(fetcher.mock.calls.some(([u, o]) => /\/research\//.test(u) && o?.method !== 'GET')).toBe(false);
 expect(view.container.querySelector('.cm-content')?.textContent).toBe(yaml);
});
it('restores matching saved asset previews in a fresh tab without submitting a render', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/editor/previews/')) return response({ status: 'hit', canonical_hash: validation.canonical_hash, receipt: {
      canonical_hash: validation.canonical_hash, cache_key: 'saved-render', options: { view: 'isometric', resolution: 1024, asset_views: {} },
      input_hash: 'hash', warnings: [], assets: [{ id: 'table', artifact_id: 'table-image', url: '/api/editor/artifacts/table-image' }],
      scene: { artifact_id: 'scene-image', url: '/api/editor/artifacts/scene-image' },
    } });
    return base(url, init);
  });
  const view = mountEditor(fetcher);
  expect(await screen.findByRole('img', { name: 'table snapshot' })).toHaveAttribute('src', '/api/editor/artifacts/table-image');
  fireEvent.change(screen.getByLabelText('Preview mode'), { target: { value: 'scene' } });
  expect(screen.getByText('Matches current canonical scene and camera options')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: 'Neo4j query' }));
  await screen.findByRole('heading', { name: 'Neo4j query' });
  fireEvent.click(screen.getByRole('link', { name: 'Environment editor' }));
  await screen.findByRole('img', { name: 'scene snapshot saved-render' });
  expect(screen.getByLabelText('Preview mode')).toHaveValue('scene');
  view.unmount();
  mountEditor(fetcher);
  await screen.findByRole('img', { name: 'table snapshot' });
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});

it('restores explicitly historical previews without calling them current or submitting automatic jobs', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { snapshots: true } });
    if (url.includes('/editor/previews/')) {
      const query = new URL(url, 'http://localhost').searchParams;
      return response({ status: 'historical', canonical_hash: validation.canonical_hash, receipt: {
        canonical_hash: validation.canonical_hash, cache_key: 'saved-history', freshness: 'unverified_assets',
        options: { view: query.get('view'), resolution: Number(query.get('resolution')), asset_views: JSON.parse(query.get('asset_views')!) },
        warnings: [], assets: [{ id: 'table', artifact_id: 'table-history', url: '/api/editor/artifacts/table-history' }],
        scene: { artifact_id: 'scene-history', url: '/api/editor/artifacts/scene-history' },
      } });
    }
    return base(url, init);
  });
  const view = mountEditor(fetcher);
  expect(await screen.findByRole('img', { name: 'table snapshot' })).toHaveAttribute('src', '/api/editor/artifacts/table-history');
  expect(screen.getByText('Historical preview · asset freshness unverified')).toBeInTheDocument();
  expect(screen.queryByText(/Saved previews match the validated scene/)).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Preview mode'), { target: { value: 'scene' } });
  expect(screen.getByRole('img', { name: 'scene snapshot saved-history' })).toBeInTheDocument();
  expect(screen.queryByText('Matches current draft')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' }));
  fireEvent.change(screen.getByLabelText('Scene camera'), { target: { value: 'top' } });
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('view=top'))).toBe(true));
  await screen.findByRole('img', { name: 'scene snapshot saved-history' });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 1700)); });
  fireEvent.click(screen.getByRole('link', { name: 'Neo4j query' }));
  await screen.findByRole('heading', { name: 'Neo4j query' });
  fireEvent.click(screen.getByRole('link', { name: 'Environment editor' }));
  await screen.findByRole('img', { name: 'scene snapshot saved-history' });
  expect(screen.getByLabelText('Preview mode')).toHaveValue('scene');
  expect(screen.getByLabelText('Scene camera')).toHaveValue('top');
  view.unmount();
  sessionStorage.clear();
  mountEditor(fetcher);
  await screen.findByRole('img', { name: 'table snapshot' });
  expect(screen.getByText('Historical preview · asset freshness unverified')).toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});

it.each(['hit', 'historical'])('uses the read-only %s catalogue without journal fallback after a miss', async (status) => {
  const base = editorServer();
  let hit = true;
  const hash = 'a'.repeat(64);
  const receipt = { input_hash: 'hash', canonical_hash: hash, cache_key: 'cache',
    freshness: status === 'historical' ? 'unverified_assets' : 'verified_assets',
    options: { view: 'isometric', resolution: 1024, asset_views: {} },
    assets: [{ id: 'table', artifact_id: 'catalogue-table', url: '/api/editor/artifacts/catalogue-table' }],
    scene: null, warnings: [] };
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/editor/documents/')) return response({ ...(await (await base(url, init)).json()), validation: { ...validation, canonical_hash: hash } });
    if (url.includes('/editor/previews/')) return response({ status: hit ? status : 'miss', canonical_hash: hash, receipt: hit ? receipt : null });
    // A matching journal receipt must never override authoritative invalidation.
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', event_cursor: 1, jobs: [{
      id: 'old', kind: 'snapshots', status: 'succeeded', stage: 'complete', workspace_id: 'default',
      inputs: { document_id: 'frozen-fixture', canonical_hash: hash }, result: receipt,
    }] });
    return base(url, init);
  });
  const view = mountEditor(fetcher);
  expect(await screen.findByRole('img', { name: 'table snapshot' })).toHaveAttribute('src', '/api/editor/artifacts/catalogue-table');
  const lookup = fetcher.mock.calls.find(([url]) => url.includes('/editor/previews/'));
  expect(lookup?.[0]).toContain(`/editor/previews/${hash}?view=isometric&resolution=1024&asset_views=`);
  expect(lookup?.[1]?.method).toBe('GET');
  hit = false;
  fireEvent.click(screen.getByRole('button', { name: 'Refresh saved previews' }));
  await screen.findByText('No saved previews for these camera options.');
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  view.unmount(); hit = false; mountEditor(fetcher);
  await screen.findByText('No saved previews for these camera options.');
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});

it('switches asset/scene previews and submits frozen camera options without editing YAML', async () => {
  const base = editorServer();
  const hash = 'b'.repeat(64);
  let release: (() => void) | undefined;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { snapshots: true } });
    if (url.includes('/editor/documents/')) return response({ ...(await (await base(url, init)).json()), validation: { ...validation, canonical_hash: hash } });
    if (url.includes('/editor/previews/')) return response({ status: 'miss', canonical_hash: hash, receipt: null });
    if (url.endsWith('/session/activity')) await new Promise<void>((resolve) => { release = resolve; });
    if (url.endsWith('/editor/snapshots')) return response({ id: 'render', kind: 'snapshots', workspace_id: 'default', status: 'queued', stage: 'queued', inputs: {} });
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  fireEvent.change(screen.getByLabelText('Preview mode'), { target: { value: 'scene' } });
  expect(screen.queryByText('No saved preview', { exact: true })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Scene camera'), { target: { value: 'top' } });
  fireEvent.change(screen.getByLabelText('Image resolution'), { target: { value: '512' } });
  fireEvent.change(screen.getByLabelText('Preview mode'), { target: { value: 'assets' } });
  fireEvent.change(screen.getByLabelText('Camera for table'), { target: { value: 'front' } });
  fireEvent.click(screen.getByRole('button', { name: 'Render snapshots' }));
  await waitFor(() => expect(release).toBeDefined());
  fireEvent.change(screen.getByLabelText('Scene camera'), { target: { value: 'side' } });
  await act(async () => release!());
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(0);
  release = undefined;
  fireEvent.click(await screen.findByRole('button', { name: 'Retry exact snapshot request' }));
  await waitFor(() => expect(release).toBeDefined());
  await act(async () => release!());
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith('/editor/snapshots'))).toBe(true));
  const request = fetcher.mock.calls.find(([url]) => url.endsWith('/editor/snapshots'))!;
  expect(JSON.parse(String(request[1]?.body))).toMatchObject({ yaml_text: 'env_name: real_document', document_id: 'frozen-fixture',
    options: { view: 'top', resolution: 512, asset_views: { table: 'front' } } });
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('env_name: real_document');
});

it.each(['historical-missing', 'historical-verified', 'hit-unverified', 'unknown-freshness'])('rejects inconsistent freshness %s rather than displaying it as current', async (failure) => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/editor/previews/')) return response({
      status: failure.startsWith('historical') ? 'historical' : 'hit', canonical_hash: validation.canonical_hash,
      receipt: { canonical_hash: validation.canonical_hash, options: { view: 'isometric', resolution: 1024, asset_views: {} },
        freshness: failure === 'historical-missing' ? undefined : failure === 'historical-verified' ? 'verified_assets'
          : failure === 'hit-unverified' ? 'unverified_assets' : 'unknown',
        assets: [{ id: 'table', artifact_id: 'unsafe', url: '/api/editor/artifacts/unsafe' }], scene: null, warnings: [],
      },
    });
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByText(/Preview catalogue unavailable/);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});

it.each(['hash', 'options', 'malformed', 'network'])('fails closed for a %s catalogue response even with matching journal data', async (failure) => {
  const base = editorServer();
  const hash = validation.canonical_hash;
  const receipt = { canonical_hash: hash, cache_key: 'unsafe', options: { view: 'isometric', resolution: 1024, asset_views: {} },
    assets: [{ id: 'table', artifact_id: 'unsafe', url: '/api/editor/artifacts/unsafe' }], scene: null, warnings: [] };
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/editor/previews/')) {
      if (failure === 'network') throw new TypeError('catalogue offline');
      return response({ status: 'hit', canonical_hash: hash, receipt: { ...receipt,
        ...(failure === 'hash' ? { canonical_hash: 'd'.repeat(64) } : failure === 'options' ? { options: { ...receipt.options, view: 'top' } } : { assets: [null] }),
      } });
    }
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', event_cursor: 1, jobs: [{
      id: 'old', kind: 'snapshots', status: 'succeeded', stage: 'complete', workspace_id: 'default',
      inputs: { canonical_hash: hash, document_id: 'frozen-fixture' }, result: { ...receipt, input_hash: 'hash' },
    }] });
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByText(/Preview catalogue unavailable/);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
});

it('does not queue another snapshot while a workspace render is already active', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { snapshots: true } });
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', event_cursor: 1, jobs: [{
      id: 'other-tab-render', kind: 'snapshots', status: 'running', stage: 'rendering', workspace_id: 'default', inputs: {},
    }] });
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  expect(screen.getByRole('button', { name: 'Render snapshots' })).toBeDisabled();
  expect(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' })).toBeDisabled();
});

it('revokes automatic preview consent when the session ends', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { snapshots: true } });
    if (url === '/api/session' && init?.method === 'DELETE') return new Response(null, { status: 204 });
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' }));
  expect(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' })).toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: 'End session' }));
  await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' })).not.toBeChecked());
});

it('requires opt-in for automatic previews and cancels the accepted job through its existing route', async () => {
  const base = editorServer();
  const hash = 'c'.repeat(64);
  let status = 'queued';
  const job = () => ({ id: 'auto-render', kind: 'snapshots', workspace_id: 'default', status, stage: status, inputs: {} });
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { snapshots: true } });
    if (url.includes('/editor/documents/')) return response({ ...(await (await base(url, init)).json()), validation: { ...validation, canonical_hash: hash } });
    if (url.includes('/editor/previews/')) return response({ status: 'miss', canonical_hash: hash, receipt: null });
    if (url.endsWith('/jobs/auto-render/cancel')) { status = 'cancel_requested'; return response(job()); }
    if (url.endsWith('/editor/snapshots') || url.endsWith('/jobs/auto-render')) return response(job());
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  const toggle = screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' });
  expect(toggle).not.toBeChecked();
  fireEvent.change(screen.getByLabelText('Scene camera'), { target: { value: 'front' } });
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(0);
  fireEvent.click(toggle);
  fireEvent.change(screen.getByLabelText('Scene camera'), { target: { value: 'top' } });
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(1), { timeout: 4000 });
  expect(screen.getByText(/1 \/ 3 automatic jobs used/)).toBeInTheDocument();
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel snapshot render' }));
  await screen.findByText('Cancellation requested; waiting for worker acknowledgment.');
  const cancel = fetcher.mock.calls.find(([url]) => url.endsWith('/jobs/auto-render/cancel'))!;
  expect((cancel[1]?.headers as Record<string, string>)['X-CSRF-Token']).toBe('csrf');
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/auto-render')).length).toBeGreaterThan(0);
});

it('recovers unsaved YAML after reload without silently changing the source context', async () => {
  const fetcher = editorServer();
  const view = mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: recovered_draft' } }));
  view.unmount();
  mountEditor(fetcher);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Restore draft' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Restore draft' }));
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('recovered_draft'));
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});

it.each(['Restore draft', 'Discard recovered draft'])(
  'keeps pending recovery across Neo4j navigation until explicit %s',
  async (decision) => {
    const fetcher = editorServer();
    const view = mountEditor(fetcher);
    await screen.findByRole('button', { name: 'Inspect Table' });
    const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
    act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: pending_recovery' } }));
    fireEvent.change(screen.getByLabelText('Describe the environment and task'), {
      target: { value: 'Keep this prompt too' },
    });
    const backup = sessionStorage.getItem('arena.editor.draft.v1');
    expect(backup).toContain('pending_recovery');
    view.unmount();
    mountEditor(fetcher);
    await screen.findByRole('button', { name: 'Restore draft' });

    async function visitNeo4jAndReturn() {
      fireEvent.click(screen.getByRole('link', { name: 'Neo4j query' }));
      await screen.findByRole('heading', { name: 'Neo4j query' });
      fireEvent.click(screen.getByRole('link', { name: 'Environment editor' }));
      await screen.findByRole('textbox', { name: 'YAML editor' });
    }

    await visitNeo4jAndReturn();
    expect(screen.getByRole('button', { name: 'Restore draft' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Save revision' })).toBeDisabled();
    expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('real_document');
    expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(backup);
    await visitNeo4jAndReturn();
    expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(backup);
    fireEvent.click(screen.getByRole('button', { name: decision }));
    await visitNeo4jAndReturn();
    expect(screen.queryByRole('button', { name: 'Restore draft' })).not.toBeInTheDocument();
    if (decision === 'Restore draft') {
      expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('pending_recovery');
      expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('Keep this prompt too');
      // Explicit recovery acquires a fresh runtime draft identity; authored and
      // frozen source fields stay exact, while v2 ownership metadata advances.
      const {draftId: _id, revision: _revision, ...fields} = JSON.parse(backup!);
      expect(JSON.parse(sessionStorage.getItem('arena.editor.draft.v1')!)).toMatchObject(fields);
    } else {
      expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('real_document');
      expect(sessionStorage.getItem('arena.editor.draft.v1')).toBeNull();
    }
    expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
  },
);

it('blocks recovery into changed included-source context and preserves a download option', async () => {
  const fetcher = editorServer();
  const view = mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: my_draft' } }));
  view.unmount();
  const changed = vi.fn(async (url: string, init?: RequestInit) => {
    const responseValue = await fetcher(url, init);
    if (url.includes('/editor/documents/')) return response({ ...(await responseValue.json()), document_id: 'changed-view' });
    return responseValue;
  });
  mountEditor(changed);
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('real_document'));
  expect(await screen.findByRole('button', { name: 'Restore draft' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Download recovered YAML' })).toBeEnabled();
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('real_document');
});

it.each(['prompt', 'YAML', 'serialized record'])(
  'offers a raw current-YAML download when %s exceeds browser storage limits',
  async (field) => {
    const fetcher = editorServer();
    mountEditor(fetcher);
    await screen.findByRole('button', { name: 'Inspect Table' });
    const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
    act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: previous_backup' } }));
    const backup = sessionStorage.getItem('arena.editor.draft.v1');
    const yaml = field === 'prompt' ? cm.state.doc.toString()
      : field === 'YAML' ? 'broken: [' + 'y'.repeat(262_145) : '\0'.repeat(100_172);
    if (field === 'prompt') {
      fireEvent.change(screen.getByLabelText('Describe the environment and task'), {
        target: { value: 'p'.repeat(16_001) },
      });
    } else {
      act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: yaml } }));
    }
    await screen.findByText(/Export your YAML before reloading/);
    expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(backup);
    const download = screen.queryByRole('button', { name: 'Download current YAML' });
    expect(download).not.toBeNull();
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:current-draft');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = createObjectURL;
      static revokeObjectURL = revokeObjectURL;
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    try {
      fireEvent.click(download!);
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      const blob = createObjectURL.mock.calls[0][0] as Blob;
      expect(blob.type).toBe('application/yaml');
      const contents = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsText(blob);
      });
      expect(contents).toBe(yaml);
      const anchor = click.mock.instances[0] as HTMLAnchorElement;
      expect(anchor.href).toBe('blob:current-draft');
      expect(anchor.download).toBe('arena-draft.yaml');
      await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith('blob:current-draft'));
      expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
    } finally {
      vi.unstubAllGlobals();
      click.mockRestore();
    }
  },
);

it('opens the real document editor with authored graph and no implicit GPU or generation work', async () => {
  const fetcher = editorServer();
  mountEditor(fetcher);
  expect(
    await screen.findByRole('heading', { name: 'ArenaEnvGraphSpec live editor' }),
  ).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent(
      'env_name: real_document',
    ),
  );
  expect(await screen.findByRole('button', { name: 'Inspect Table' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Inspect Explicit relation' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Inspect Table' }));
  expect(screen.getByRole('heading', { name: 'Node inspector' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: /Unary constraints/ })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Run integration test' })).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(
    0,
  );
});
it('keeps unsaved YAML when visiting Neo4j and returning to the editor', async () => {
  mountEditor();
  await waitFor(() =>
    expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('real_document'),
  );
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() =>
    cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: unsaved' } }),
  );
  fireEvent.click(screen.getByRole('link', { name: 'Neo4j query' }));
  await screen.findByRole('heading', { name: 'Neo4j query' });
  fireEvent.click(screen.getByRole('link', { name: 'Environment editor' }));
  await waitFor(() =>
    expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent(
      'env_name: unsaved',
    ),
  );
});
it('retains ambiguous generation across reload and retries the frozen request without a new prompt', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') { const data = await (await base(url, init)).json(); return response({ ...data, capabilities: { ...data.capabilities, generation: true } }); }
    if (url.endsWith('/editor/generate')) throw new TypeError('network lost');
    return base(url, init);
  });
  const view = mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Make a scene' } });
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  await screen.findByText('network lost');
  const body = fetcher.mock.calls.find(([url]) => url.endsWith('/editor/generate'))![1]?.body;
  view.unmount(); mountEditor(fetcher);
  const retry = await screen.findByRole('button', { name: 'Retry generation request' });
  await waitFor(() => expect(retry).toBeEnabled());
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate'))).toHaveLength(1);
  fireEvent.click(retry);
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate'))).toHaveLength(2));
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate'))[1][1]?.body).toBe(body);
});
it('requires explicit discard before replacing a rejected generation reference', async () => {
  const base = editorServer();
  const key = 'arena:editor:generate:v1';
  const previous = { payload: { prompt: 'old prompt', credential_ref: 'expired-reference', idempotency_key: 'old-request' } };
  sessionStorage.setItem(key, JSON.stringify(previous));
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/model-settings') return response({ providers: PROVIDERS, configured: true, source: 'session',
      provider: 'openai', model: 'new-model', expires_at: 9999999999, credential_ref: 'replacement-reference', session_keys_allowed: true });
    if (url.endsWith('/editor/generate')) return response({ detail: 'Temporary credential unavailable' }, 409);
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  const discard = await screen.findByRole('button', { name: 'Discard unresolved request' });
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  try {
    fireEvent.click(discard);
    expect(JSON.parse(sessionStorage.getItem(key)!)).toEqual(previous);
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('may already have been accepted'));
    confirm.mockReturnValue(true);
    fireEvent.click(discard);
    expect(sessionStorage.getItem(key)).toBeNull();
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate'))).toHaveLength(0);
    fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'new prompt' } });
    fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
    await screen.findByText('Temporary credential unavailable');
    const sent = JSON.parse(String(fetcher.mock.calls.find(([url]) => url.endsWith('/editor/generate'))![1]?.body));
    expect(sent.credential_ref).toBe('replacement-reference');
    expect(sent.idempotency_key).not.toBe('old-request');
    expect(sent.prompt).toBe('new prompt');
    expect(await screen.findByRole('button', { name: 'Discard unresolved request' })).toBeEnabled();
  } finally {
    confirm.mockRestore();
  }
});

it('uses session settings to enable generation and freezes the reference at click and ambiguous retry', async () => {
  const base = editorServer();
  let ref = 'public-ref-original';
  let release: (() => void) | undefined;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/model-settings') return response({ providers: PROVIDERS, configured: true, source: 'session',
      provider: 'openai', model: 'user-model', expires_at: 9999999999, credential_ref: ref, session_keys_allowed: true });
    if (url.endsWith('/session/activity')) await new Promise<void>(resolve => { release = resolve; });
    if (url.endsWith('/editor/generate')) throw new TypeError('network lost');
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByText(/Temporary key active/);
  await screen.findByRole('button', { name: 'Inspect Table' });
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Make a scene' } });
  expect(screen.getByRole('button', { name: 'Generate spec' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  await waitFor(() => expect(release).toBeDefined());
  ref = 'public-ref-rotated';
  fireEvent.click(screen.getByRole('button', { name: 'Refresh provider status' }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url === '/api/model-settings')).toHaveLength(2));
  act(() => release!());
  await screen.findByText('network lost');
  const original = fetcher.mock.calls.find(([url]) => url.endsWith('/editor/generate'))![1]?.body;
  expect(JSON.parse(String(original))).toMatchObject({ credential_ref: 'public-ref-original', prompt: 'Make a scene', base_yaml: 'env_name: real_document' });
  fireEvent.click(screen.getByRole('button', { name: 'Retry generation request' }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/session/activity'))).toHaveLength(2));
  act(() => release!());
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate'))).toHaveLength(2));
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate'))[1][1]?.body).toBe(original);
});

it.each(['unconfigured', 'expired', 'unavailable'])('does not trust stale editor capability when provider status is %s', async (state) => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { generation: true } });
    if (url === '/api/model-settings') return state === 'unavailable' ? response({ detail: 'offline' }, 503)
      : response({ providers: PROVIDERS, configured: state !== 'unconfigured', source: state === 'expired' ? 'session' : 'none',
        provider: state === 'expired' ? 'openai' : null, model: state === 'expired' ? 'model' : null,
        expires_at: state === 'expired' ? 1 : null, credential_ref: state === 'expired' ? 'expired-ref' : null, session_keys_allowed: true });
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  await screen.findByText(state === 'unavailable' ? /Provider settings unavailable/ : state === 'expired' ? /Temporary key expired/ : /No provider configured/);
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Make a scene' } });
  expect(screen.getByRole('button', { name: 'Generate spec' })).toBeDisabled();
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate'))).toHaveLength(0);
});

it('preserves unsaved YAML, prompt and graph when saving settings and never persists the password', async () => {
  const base = editorServer();
  let configured = false;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/model-settings') {
      if (init?.method === 'PUT') configured = true;
      return response({ providers: PROVIDERS, configured, source: configured ? 'session' : 'none', provider: configured ? 'gemini' : null,
        model: configured ? 'user-model' : null, credential_ref: configured ? 'public-ref' : null, expires_at: configured ? 9999999999 : null,
        session_keys_allowed: true });
    }
    return base(url, init);
  });
  const storage = vi.spyOn(Storage.prototype, 'setItem');
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  await screen.findByText(/No provider configured/);
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: unsaved_provider_test' } }));
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Keep my prompt' } });
  fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'gemini' } });
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'user-model' } });
  fireEvent.click(screen.getByRole('checkbox', { name: /I consent/ }));
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'dummy-editor-secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save temporary key' }));
  await screen.findByText(/Temporary key active/);
  expect(screen.getByLabelText('API key')).toHaveValue('');
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('Keep my prompt');
  expect(cm.state.doc.toString()).toBe('env_name: unsaved_provider_test');
  await screen.findByRole('button', { name: 'Inspect Table' });
  expect(JSON.stringify(storage.mock.calls)).not.toContain('dummy-editor-secret');
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
  storage.mockRestore();
});

it('freezes revision YAML and source identity at the click before asynchronous activity', async () => {
  const base = editorServer();
  let release: (() => void) | undefined;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/session/activity')) await new Promise<void>((resolve) => { release = resolve; });
    if (url.endsWith('/editor/save')) return response({ revision_id: 'frozen', download_url: '/api/editor/revisions/frozen/download' });
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => {
    fireEvent.click(screen.getByRole('button', { name: 'Save revision' }));
    cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: edited_after_click' } });
  });
  await waitFor(() => expect(release).toBeDefined());
  act(() => release!());
  await screen.findByRole('link', { name: 'Export flattened YAML' });
  const saved = JSON.parse(String(fetcher.mock.calls.find(([url]) => url.endsWith('/editor/save'))![1]?.body));
  expect(saved).toEqual({ yaml_text: 'env_name: real_document', document_id: 'frozen-fixture', expected_source_hash: 'hash' });
});

it('saves an immutable export and only applies generation after explicit review', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') {
      const data = await (await base(url, init)).json();
      return response({ ...data, capabilities: { ...data.capabilities, generation: true } });
    }
    if (url.endsWith('/editor/save'))
      return response({
        revision_id: 'rev',
        yaml_text: 'env_name: real_document',
        source_hash: 'hash',
        canonical_hash: 'a'.repeat(64),
        download_url: '/api/editor/revisions/rev/download',
      });
    if (url.endsWith('/editor/generate') || url === '/api/jobs/generation')
      return response({
        id: 'generation',
        workspace_id: 'default',
        kind: 'generate',
        status: 'succeeded',
        stage: 'complete',
        inputs: {},
        result: {
          yaml_text: 'env_name: generated',
          validation,
          warnings: [],
          publication: 'not_published',
          traces: [],
        },
      });
    return base(url, init);
  });
  mountEditor(fetcher);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save revision' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Save revision' }));
  expect(await screen.findByRole('link', { name: 'Export flattened YAML' })).toHaveAttribute(
    'href',
    '/api/editor/revisions/rev/download',
  );
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), {
    target: { value: 'Make a scene' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  expect(await screen.findByRole('button', { name: 'Apply generated YAML' })).toBeInTheDocument();
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('real_document');
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() =>
    cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: newer_draft' } }),
  );
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  fireEvent.click(screen.getByRole('button', { name: 'Apply generated YAML' }));
  expect(confirm).toHaveBeenCalled();
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('newer_draft');
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', { name: 'Apply generated YAML' }));
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('generated');
  confirm.mockRestore();
  const save = fetcher.mock.calls.find(([url]) => url.endsWith('/editor/save'))!;
  expect(JSON.parse(String(save[1]?.body))).toMatchObject({
    document_id: 'frozen-fixture',
    expected_source_hash: 'hash',
  });
  expect((save[1]?.headers as Record<string, string>)['X-CSRF-Token']).toBe('csrf');
});
it('renders only on request, shows authenticated asset and scene images, and opens zoom', async () => {
  const base = editorServer();
  let rendered = false;
  const receipt = { canonical_hash: validation.canonical_hash, cache_key: 'render', options: { view: 'isometric', resolution: 1024, asset_views: {} }, input_hash: 'hash',
    assets: [{ id: 'table', artifact_id: 'asset', url: '/api/editor/artifacts/asset' }],
    scene: { artifact_id: 'scene', url: '/api/editor/artifacts/scene' }, warnings: [] };
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') {
      const data = await (await base(url, init)).json();
      return response({ ...data, capabilities: { ...data.capabilities, snapshots: true } });
    }
    if (url.includes('/editor/previews/')) return response({ status: rendered ? 'hit' : 'miss', canonical_hash: validation.canonical_hash, receipt: rendered ? receipt : null });
    if (url.endsWith('/editor/snapshots')) rendered = true;
    if (url.endsWith('/editor/snapshots') || url === '/api/jobs/render')
      return response({
        id: 'render',
        workspace_id: 'default',
        kind: 'snapshots',
        status: 'succeeded',
        stage: 'complete',
        inputs: { document_id: 'frozen-fixture', canonical_hash: 'a'.repeat(64), yaml_text: 'env_name: real_document' },
        result: {
          input_hash: 'hash',
          assets: [{ id: 'table', artifact_id: 'asset', url: '/api/editor/artifacts/asset' }],
          scene: { artifact_id: 'scene', url: '/api/editor/artifacts/scene' },
          warnings: [],
        },
      });
    return base(url, init);
  });
  mountEditor(fetcher);
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Render snapshots' })).toBeEnabled(),
  );
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Render snapshots' }).compareDocumentPosition(
    document.querySelector('.asset-grid')!,
  ) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Render snapshots' }));
  expect(await screen.findByRole('img', { name: 'table snapshot' })).toHaveAttribute(
    'src',
    '/api/editor/artifacts/asset',
  );
  fireEvent.change(screen.getByLabelText('Preview mode'), { target: { value: 'scene' } });
  fireEvent.click(await screen.findByRole('button', { name: /Zoom scene snapshot/ }));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Close image' }));
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => cm.dispatch({ changes: { from: cm.state.doc.length, insert: '\n# changed' } }));
  expect(screen.getByText('Stale · draft changed since this render')).toBeInTheDocument();
});
it('queries Neo4j separately with parameters and switches table results to an interactive graph', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/graph/status')) return response({ available: true, message: 'Connected' });
    if (url.endsWith('/graph/examples'))
      return response({
        queries: [
          {
            id: 'nodes',
            name: 'Nodes',
            query: 'MATCH (n) RETURN n LIMIT $limit',
            params: { limit: 2 },
          },
        ],
      });
    if (url.endsWith('/graph/query'))
      return response({
        columns: ['n'],
        rows: [[{ name: 'Persisted table' }]],
        graph: {
          nodes: [
            {
              id: 'persisted',
              label: 'Persisted table',
              role: 'Asset',
              properties: { name: 'Persisted table' },
            },
          ],
          edges: [],
        },
        elapsed_ms: 2,
        truncated: true,
        read_only: true,
      });
    return base(url, init);
  });
  mountEditor(fetcher, '/neo4j');
  expect(await screen.findByRole('heading', { name: 'Neo4j query' })).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Run read-only query' })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Run read-only query' }));
  expect(await screen.findByText(/Results truncated/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('tab', { name: 'Graph' }));
  fireEvent.click(screen.getByRole('button', { name: 'Inspect Persisted table' }));
  expect(screen.getByRole('heading', { name: 'Node inspector' })).toBeInTheDocument();
  expect(screen.queryByLabelText('Authored spatial graph')).not.toBeInTheDocument();
  expect(
    JSON.parse(String(fetcher.mock.calls.find(([url]) => url.endsWith('/graph/query'))![1]?.body)),
  ).toEqual({ query: 'MATCH (n) RETURN n LIMIT $limit', params: { limit: 2 } });
});
