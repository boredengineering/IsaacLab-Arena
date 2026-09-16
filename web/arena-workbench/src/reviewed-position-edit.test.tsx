import { createHash, webcrypto } from 'node:crypto';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { AuthoredInspector } from './authored-inspector';
import type { Validation } from './editor-contracts';
import { ReviewedPositionEdit, type PositionEditBinding } from './reviewed-position-edit';

beforeEach(() => { vi.stubGlobal('crypto', webcrypto); });
const hash = (text: string) => createHash('sha256').update(text).digest('hex');
const draft = '# keep bytes\r\nenv_name: review_table\r\nembodiment: {id: robot, registry_name: franka}\r\nbackground:\r\n  id: desk\r\n  registry_name: table\r\n  params:\r\n    initial_pose:\r\n      position_xyz: [0.5, 0, 0] # meters\r\n      rotation_xyzw: [0, 0, 0, 1]\r\nobjects: []\r\nrelations: []\r\ntask: {composition: atomic, subtasks: [{kind: NoTask, params: {}}]}\r\n';
const candidate = draft.replace('[0.5, 0, 0]', '[1.25, 0, 0]');
function validation(text = draft): Validation {
  const properties = {id: 'desk', registry_name: 'table', params: {initial_pose: {position_xyz: [text === candidate ? 1.25 : 0.5, 0, 0], rotation_xyzw: [0, 0, 0, 1]}}};
  return {valid: true, source_hash: hash(text), canonical_hash: 'b'.repeat(64), errors: [], warnings: ['Schema only'], spec: {}, summary: 'Schema valid',
    assets: [{...properties, role: 'background', properties}], relations: [], reified_relations: [], tasks: [{kind: 'NoTask', params: {}}], graph: {nodes: [], edges: []}};
}
function mount(inspector = false) {
  let release!: (r: Response) => void;
  const fetcher = vi.fn((_url: string, _init?: RequestInit) => new Promise<Response>(resolve => { release = resolve; }));
  const api = new ApiClient(fetcher as typeof fetch);
  api.session = {session_id: 's', csrf_token: 'dummy', expires_at: 9999999999};
  const onApply = vi.fn(() => true);
  let binding: PositionEditBinding = { api, draft, documentId: 'frozen-view', sourceHash: hash(draft), bindingKey: 'owner:1', optionsKey: 'options:1', active: true, validationReady: true, isCurrent: () => true, onApply };
  let current: Validation | null = validation(); let selectedId = 'desk';
  const tree = () => inspector ? <AuthoredInspector editing={binding} validation={current} bindingKey={binding.bindingKey} onFocusSpecification={() => {}} /> : <ReviewedPositionEdit binding={binding} validation={current} selectedId={selectedId} />;
  const view = render(tree());
  if (inspector) fireEvent.change(screen.getByRole('combobox', {name: 'Authored asset'}), {target: {value: 'desk'}});
  return {...view, api, fetcher, onApply, binding,
    change: (changes: Partial<PositionEditBinding>) => {binding = {...binding, ...changes}; view.rerender(tree());},
    validate: (v: Validation | null) => {current = v; view.rerender(tree());},
    select: (id: string) => { selectedId = id; view.rerender(tree()); },
    respond: async (v: unknown = validation(candidate), status = 200) => { await act(async () => release(new Response(JSON.stringify(v), {status}))); },
  };
}
async function propose(view: ReturnType<typeof mount>) {
  fireEvent.change(screen.getByLabelText('Proposed coordinate (m)'), {target: {value: '1.25'}});
  fireEvent.click(screen.getByRole('button', {name: 'Validate position proposal'}));
  await waitFor(() => expect(view.fetcher).toHaveBeenCalledTimes(1));
}
it('does not grant stale controls a same-ID replacement session during a local input rerender', async () => {
  const view = mount();
  view.api.session = {...view.api.session!};
  fireEvent.change(screen.getByLabelText('Proposed coordinate (m)'), {target: {value: '1.25'}});
  fireEvent.click(screen.getByRole('button', {name: 'Validate position proposal'}));
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(view.fetcher).not.toHaveBeenCalled();
});
it.each(['source', 'document', 'draft', 'client', 'active', 'options', 'binding', 'selection', 'validation'] as const)('never revives pending proposals through %s A→B→A', async gate => {
  const view = mount(); await propose(view);
  const original = view.binding;
  if (gate === 'selection') { view.select('other'); view.select('desk'); }
  else if (gate === 'validation') { view.validate(null); view.validate(validation()); }
  else {
    const changes: Partial<PositionEditBinding> = gate === 'source' ? {sourceHash: 'c'.repeat(64)} : gate === 'document' ? {documentId: 'other-view'} : gate === 'draft' ? {draft: draft + '# B'} : gate === 'client' ? {api: new ApiClient()} : gate === 'active' ? {active: false} : gate === 'options' ? {optionsKey: 'B'} : {bindingKey: 'B'};
    view.change(changes); view.change(original);
  }
  await view.respond();
  expect(screen.queryByRole('region', {name: 'Exact source diff'})).not.toBeInTheDocument();
  expect(view.onApply).not.toHaveBeenCalled();
});
it.each(['', 'NaN', 'Infinity', '-Infinity', '1e999'])('refuses nonfinite/empty input %s', value => {
  const view = mount(); fireEvent.change(screen.getByLabelText('Proposed coordinate (m)'), {target: {value}});
  expect(screen.getByRole('button', {name: 'Validate position proposal'})).toBeDisabled();
  expect(view.fetcher).not.toHaveBeenCalled();
});
it.each(['invalid', 'failed', 'wrong hash', 'wrong projection', 'malformed'] as const)('does not apply %s candidate validation', async kind => {
  const view = mount(); await propose(view);
  const v = validation(candidate);
  if (kind === 'invalid') {v.valid = false; v.errors = ['Candidate rejected'];}
  if (kind === 'wrong hash') v.source_hash = hash(draft);
  if (kind === 'wrong projection') v.assets[0].registry_name = 'unknown';
  await view.respond(kind === 'malformed' ? {valid: true} : v, kind === 'failed' ? 503 : 200);
  expect(screen.getByRole('button', {name: 'Apply reviewed position'})).toBeDisabled();
  expect(screen.getByRole('checkbox', {name: 'I reviewed this exact source diff'})).toBeDisabled();
  expect(view.onApply).not.toHaveBeenCalled();
});
it.each(['session', 'inactive callback', 'unmount'] as const)('drops late successful validation after %s without rerender', async gate => {
  const view = mount(); await propose(view);
  if (gate === 'session') view.api.session = {...view.api.session!};
  if (gate === 'inactive callback') view.binding.isCurrent = () => false;
  if (gate === 'unmount') view.unmount();
  await view.respond();
  expect(screen.queryByText('Candidate schema valid · not runtime-validated')).not.toBeInTheDocument();
  expect(view.onApply).not.toHaveBeenCalled();
});
it('retires consent when value or axis goes A→B→A and blocks old-session Apply before rerender', async () => {
  const view = mount(); await propose(view); await view.respond();
  fireEvent.click(screen.getByRole('checkbox', {name: 'I reviewed this exact source diff'}));
  view.api.session = {...view.api.session!};
  fireEvent.click(screen.getByRole('button', {name: 'Apply reviewed position'}));
  expect(view.onApply).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('Position axis'), {target: {value: '1'}});
  fireEvent.change(screen.getByLabelText('Position axis'), {target: {value: '0'}});
  expect(screen.queryByRole('region', {name: 'Exact source diff'})).not.toBeInTheDocument();
});
it('requires current draft hash and frozen source provenance before POST', async () => {
  const view = mount(); view.validate({...validation(), source_hash: 'd'.repeat(64)});
  fireEvent.change(screen.getByLabelText('Proposed coordinate (m)'), {target: {value: '1.25'}});
  fireEvent.click(screen.getByRole('button', {name: 'Validate position proposal'}));
  await screen.findByText('Candidate validation failed');
  expect(view.fetcher).not.toHaveBeenCalled();
  view.change({documentId: ''});
  expect(screen.queryByRole('button', {name: 'Validate position proposal'})).not.toBeInTheDocument();
});
// Invoke captured production handlers without fireEvent's discrete-event flush.
function retainedHandler(node: HTMLElement, name: 'onClick' | 'onChange') {
  const key = Object.keys(node).find(key => key.startsWith('__reactProps$'))!;
  return (node as unknown as Record<string, Record<string, (event?: unknown) => void>>)[key][name];
}
it.each(['axis', 'value'])('rejects retained proposal validation after a same-turn %s change', async gate => {
  const view = mount();
  fireEvent.change(screen.getByLabelText('Proposed coordinate (m)'), {target: {value: '1.25'}});
  const proposeOld = retainedHandler(screen.getByRole('button', {name: 'Validate position proposal'}), 'onClick');
  const change = retainedHandler(screen.getByLabelText(gate === 'axis' ? 'Position axis' : 'Proposed coordinate (m)'), 'onChange');
  await act(async () => {
    change({target: {value: '1'}});
    proposeOld();
    await new Promise(resolve => setTimeout(resolve, 30));
  });
  expect(view.fetcher).not.toHaveBeenCalled();
});
it('withdraws consent immediately while preserving exact review diagnostics for fresh consent', async () => {
  const view = mount(); await propose(view); await view.respond();
  const checkbox = () => screen.getByRole('checkbox', {name: 'I reviewed this exact source diff'});
  fireEvent.click(checkbox());
  const oldApply = retainedHandler(screen.getByRole('button', {name: 'Apply reviewed position'}), 'onClick');
  const withdraw = retainedHandler(checkbox(), 'onChange');
  act(() => {withdraw({target: {checked: false}}); oldApply();});
  expect(view.onApply).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Candidate root YAML')).toHaveTextContent('1.25');
  expect(screen.getByRole('region', {name: 'Candidate validation'})).toHaveTextContent('Schema only');
  expect(checkbox()).not.toBeChecked();
  fireEvent.click(checkbox());
  act(() => oldApply());
  expect(view.onApply).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', {name: 'Apply reviewed position'}));
  expect(view.onApply).toHaveBeenCalledExactlyOnceWith(candidate);
});
it.each(['selection', 'consent', 'axis', 'value'] as const)('retires retained Apply before React renders %s A→B→A', async gate => {
  const view = mount(true); await propose(view); await view.respond();
  fireEvent.click(screen.getByRole('checkbox', {name: 'I reviewed this exact source diff'}));
  const apply = retainedHandler(screen.getByRole('button', {name: 'Apply reviewed position'}), 'onClick');
  const node = gate === 'selection' ? screen.getByLabelText('Authored asset') : gate === 'consent' ? screen.getByRole('checkbox', {name: 'I reviewed this exact source diff'}) : screen.getByLabelText(gate === 'axis' ? 'Position axis' : 'Proposed coordinate (m)');
  const change = retainedHandler(node, 'onChange');
  act(() => {
    change({target: {value: gate === 'selection' ? '' : '1', checked: false}});
    change({target: {value: gate === 'selection' ? 'desk' : gate === 'axis' ? '0' : '1.25', checked: true}});
    apply();
    expect(view.onApply).not.toHaveBeenCalled();
  });
  expect(view.onApply).not.toHaveBeenCalled();
});
it('retires the real inspector selection synchronously even through batched A→B→A before Apply', async () => {
  const view = mount(true); await propose(view); await view.respond();
  fireEvent.click(screen.getByRole('checkbox', {name: 'I reviewed this exact source diff'}));
  const apply = screen.getByRole('button', {name: 'Apply reviewed position'});
  act(() => {
    fireEvent.change(screen.getByRole('combobox', {name: 'Authored asset'}), {target: {value: ''}});
    fireEvent.change(screen.getByRole('combobox', {name: 'Authored asset'}), {target: {value: 'desk'}});
    fireEvent.click(apply);
  });
  expect(view.onApply).not.toHaveBeenCalled();
  expect(screen.queryByRole('region', {name: 'Exact source diff'})).not.toBeInTheDocument();
});
it.each(['pending', 'failed'] as const)('retires a validated candidate while current validation is %s, including return to ready', async () => {
  const view = mount(); await propose(view); await view.respond();
  fireEvent.click(screen.getByRole('checkbox', {name: 'I reviewed this exact source diff'}));
  view.change({validationReady: false}); view.change({validationReady: true});
  expect(screen.queryByRole('button', {name: 'Apply reviewed position'})).not.toBeInTheDocument();
  expect(view.onApply).not.toHaveBeenCalled();
});
it('rechecks ownership after asynchronous source hashing before dispatch', async () => {
  const view = mount();
  const digest = crypto.subtle.digest.bind(crypto.subtle);
  let release!: () => void;
  const delayed = vi.spyOn(crypto.subtle, 'digest').mockImplementationOnce(async (...args) => {
    const result = await digest(...args);
    await new Promise<void>(resolve => {release = resolve;}); return result;
  });
  fireEvent.change(screen.getByLabelText('Proposed coordinate (m)'), {target: {value: '1.25'}});
  fireEvent.click(screen.getByRole('button', {name: 'Validate position proposal'}));
  await waitFor(() => expect(release).toBeDefined());
  view.api.session = {...view.api.session!};
  await act(async () => release());
  expect(view.fetcher).not.toHaveBeenCalled();
  delayed.mockRestore();
});
it('validates the exact root candidate with the frozen view then requires diff consent and explicit Apply', async () => {
  const view = mount();
  await propose(view);
  expect(view.fetcher.mock.calls[0][0]).toBe('/api/editor/validate');
  const init = view.fetcher.mock.calls[0][1]!;
  expect(JSON.parse(String(init.body))).toEqual({yaml_text: candidate, document_id: 'frozen-view'});
  expect(init.headers).toMatchObject({'X-CSRF-Token': 'dummy'});
  expect(screen.getByRole('button', {name: 'Apply reviewed position'})).toBeDisabled();
  expect(view.onApply).not.toHaveBeenCalled();
  await view.respond();
  expect(screen.getByLabelText('Original root YAML').textContent).toBe(draft);
  expect(screen.getByLabelText('Candidate root YAML').textContent).toBe(candidate);
  expect(screen.getByRole('region', {name: 'Candidate validation'})).toHaveTextContent('Schema only');
  expect(screen.getByRole('button', {name: 'Apply reviewed position'})).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox', {name: 'I reviewed this exact source diff'}));
  fireEvent.click(screen.getByRole('button', {name: 'Apply reviewed position'}));
  expect(view.onApply).toHaveBeenCalledExactlyOnceWith(candidate);
  expect(screen.getByRole('button', {name: 'Apply reviewed position'})).toBeDisabled();
  expect(view.fetcher).toHaveBeenCalledTimes(1);
});
