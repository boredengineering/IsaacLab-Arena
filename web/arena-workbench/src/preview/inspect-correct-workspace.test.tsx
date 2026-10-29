import { fireEvent, render, screen, within } from '@testing-library/react';
import { useEffect, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { InspectCorrectWorkspace } from './inspect-correct-workspace';
import { inspectionVersions } from './inspection-data';
import type { PreviewSelection } from './types';

function Harness({ source = inspectionVersions[0], initial, child }: { source?: PreviewSelection | null; initial?: string; child?: React.ReactNode }) {
 const [draft, setDraft] = useState(initial ?? source?.yaml ?? '');
 const [expanded, setExpanded] = useState(false);
 return <InspectCorrectWorkspace selection={source} draft={draft} onDraft={setDraft} expanded={expanded} onExpandViewport={() => setExpanded(true)} onReturnToEditor={() => setExpanded(false)} onLoadExample={vi.fn()}>{child ?? <div>Persistent viewport</div>}</InspectCorrectWorkspace>;
}
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));
const change = (name: string, value: string) => fireEvent.change(screen.getByLabelText(name), { target: { value } });

describe('offline inspect and correct', () => {
 it('does not submit a containing form through local workspace controls', () => {
  const submit = vi.fn((event: React.FormEvent) => event.preventDefault());
  render(<form onSubmit={submit}><Harness /></form>);
  click('Select cube'); click('Keep recovery copy'); click('Expand viewport'); click('Return to editor');
  expect(submit).not.toHaveBeenCalled();
 });
 it('renders multiple findings on one authored field without duplicate React keys', () => {
  const error = vi.spyOn(console, 'error').mockImplementation(() => {});
  const doc = JSON.parse(inspectionVersions[0].yaml); doc.assets.forEach((a: { id: string }) => { a.id = ''; });
  render(<Harness initial={JSON.stringify(doc)} />);
  expect(screen.getAllByText(/Duplicate authored ID/)).toHaveLength(2);
  expect(error).not.toHaveBeenCalled();
 });
 it('focuses the specification rather than a different asset when a required key is absent', () => {
  const doc = JSON.parse(inspectionVersions[0].yaml); delete doc.assets[0].id;
  const raw = JSON.stringify(doc); render(<Harness initial={raw} />);
  click('Inspect finding: assets[0].id');
  const editor = screen.getByLabelText('Draft YAML') as HTMLTextAreaElement;
  expect(editor).toHaveFocus(); expect(editor.selectionStart).toBe(0); expect(editor.selectionEnd).toBe(raw.length);
 });
 it('independently hides retained panels through expand and return without remounting children', () => {
  const mount = vi.fn(), unmount = vi.fn();
  function Child() { useEffect(() => { mount(); return unmount; }, []); return <div data-testid="retained-child" />; }
  render(<Harness child={<Child />} />);
  const root = screen.getByRole('region', { name: 'Inspect and correct workspace' });
  const specification = screen.getByRole('region', { name: 'Specification' });
  const inspector = screen.getByRole('complementary', { name: 'Authored asset inspector' });
  const editor = screen.getByLabelText('Draft YAML');
  const child = screen.getByTestId('retained-child');
  click('Select cube'); change('Proposed value', '0.6'); click('Review pose change'); click('Keep recovery copy');
  const review = screen.getByRole('region', { name: 'Frozen pose review' });
  const copy = screen.getByRole('region', { name: 'Memory recovery copy' });
  click('Hide specification');
  expect(specification).toHaveAttribute('hidden'); expect(inspector).not.toHaveAttribute('hidden');
  expect(root).toHaveClass('specification-collapsed');
  click('Hide inspector'); expect(inspector).toHaveAttribute('hidden'); expect(root).toHaveClass('inspector-collapsed');
  click('Expand viewport'); click('Return to editor');
  expect(specification).toHaveAttribute('hidden'); expect(inspector).toHaveAttribute('hidden');
  click('Show specification');
  expect(specification).not.toHaveAttribute('hidden'); expect(inspector).toHaveAttribute('hidden');
  click('Show inspector');
  expect(root).not.toHaveClass('specification-collapsed'); expect(root).not.toHaveClass('inspector-collapsed');
  expect(screen.getByRole('region', { name: 'Specification' })).toBe(specification);
  expect(screen.getByRole('complementary', { name: 'Authored asset inspector' })).toBe(inspector);
  expect(screen.getByLabelText('Draft YAML')).toBe(editor); expect(editor).toHaveValue(inspectionVersions[0].yaml);
  expect(screen.getByRole('region', { name: 'Frozen pose review' })).toBe(review);
  expect(screen.getByRole('region', { name: 'Memory recovery copy' })).toBe(copy);
  expect(screen.getByTestId('retained-child')).toBe(child);
  expect(mount).toHaveBeenCalledOnce(); expect(unmount).not.toHaveBeenCalled();
 });
 it('sizes only the desktop specification layout without mutating draft or pose review', () => {
  const onDraft = vi.fn();
  const props = { selection: inspectionVersions[0], draft: inspectionVersions[0].yaml, onDraft, expanded: false, onExpandViewport: vi.fn(), onReturnToEditor: vi.fn(), onLoadExample: vi.fn(), children: <div /> };
  const { rerender } = render(<InspectCorrectWorkspace {...props} />);
  const root = screen.getByRole('region', { name: 'Inspect and correct workspace' });
  const width = screen.getByRole('slider', { name: 'Specification width' });
  expect(width).toHaveAttribute('type', 'range'); expect(width).toHaveAttribute('min', '25'); expect(width).toHaveAttribute('max', '40');
  expect(width).toHaveValue('30'); expect(root.style.getPropertyValue('--inspect-spec-width')).toBe('30%');
  width.focus(); expect(width).toHaveFocus(); expect(width.tabIndex).toBe(0);
  click('Select cube'); change('Proposed value', '0.6'); click('Review pose change');
  fireEvent.click(screen.getByLabelText('I consent to replace the draft with this reviewed pose change'));
  const review = screen.getByRole('region', { name: 'Frozen pose review' }).textContent;
  for (const value of ['25', '40', '35']) {
   change('Specification width', value); expect(root.style.getPropertyValue('--inspect-spec-width')).toBe(`${value}%`);
  }
  expect(screen.getByLabelText('Proposed value')).toHaveValue(0.6);
  expect(screen.getByRole('region', { name: 'Frozen pose review' }).textContent).toBe(review);
  expect(screen.getByRole('button', { name: 'Apply reviewed pose change' })).toBeEnabled();
  click('Hide specification'); expect(width).toBeDisabled(); click('Show specification'); expect(width).toBeEnabled();
  rerender(<InspectCorrectWorkspace {...props} expanded />); expect(width).toBeDisabled();
  rerender(<InspectCorrectWorkspace {...props} />); expect(width).toBeEnabled(); expect(width).toHaveValue('35');
  expect(screen.getByLabelText('Draft YAML')).toHaveValue(props.draft); expect(onDraft).not.toHaveBeenCalled();
 });
 it('preserves review, draft and child identity during viewport expansion', () => {
  render(<Harness child={<div data-testid="same-child" />} />);
  const child = screen.getByTestId('same-child'); click('Select cube'); change('Proposed value', '0.6'); click('Review pose change');
  click('Keep recovery copy'); click('Expand viewport');
  expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument(); expect(screen.getByTestId('same-child')).toBe(child);
  click('Return to editor'); expect(screen.getByLabelText('Draft YAML')).toHaveValue(inspectionVersions[0].yaml);
  expect(screen.getByRole('region', { name: 'Frozen pose review' })).toHaveTextContent('0.6');
  expect(screen.getByRole('region', { name: 'Memory recovery copy' })).toBeInTheDocument();
 });
 it('bounds pose inputs, permits rotation edits and re-reviews a stale same-source recovery', () => {
  render(<Harness />); click('Select cube');
  expect(screen.getByRole('button', { name: 'Review pose change' })).toBeDisabled();
  change('Proposed value', '1000001'); expect(screen.getByRole('button', { name: 'Review pose change' })).toBeDisabled();
  change('Proposed value', '0.25'); expect(screen.getByRole('button', { name: 'Review pose change' })).toBeDisabled();
  change('Pose field', 'rotationDegrees'); change('Pose axis', '2'); change('Proposed value', '90');
  click('Review pose change'); fireEvent.click(screen.getByLabelText('I consent to replace the draft with this reviewed pose change')); click('Apply reviewed pose change');
  expect(JSON.parse((screen.getByLabelText('Draft YAML') as HTMLTextAreaElement).value).assets[1].pose.rotationDegrees).toEqual([0, 0, 90]);
  click('Keep recovery copy'); click('Review recovery copy'); change('Draft YAML', 'later invalid draft');
  expect(screen.getByRole('button', { name: 'Restore reviewed recovery copy' })).toBeDisabled();
  click('Review recovery copy'); fireEvent.click(screen.getByLabelText('I consent to replace the current draft with this recovery copy')); click('Restore reviewed recovery copy');
  expect(JSON.parse((screen.getByLabelText('Draft YAML') as HTMLTextAreaElement).value).assets[1].pose.rotationDegrees).toEqual([0, 0, 90]);
 });
 it('focuses the exact authored field and rejects ambiguous duplicate JSON keys', () => {
  const doc = JSON.parse(inspectionVersions[0].yaml); doc.assets[1].scale = [0, 1, 1];
  const raw = JSON.stringify(doc, null, 2);
  render(<Harness initial={raw} />); click('Inspect finding: assets[1].scale');
  const editor = screen.getByLabelText('Draft YAML') as HTMLTextAreaElement;
  expect(editor.value.slice(editor.selectionStart, editor.selectionEnd)).toBe('"scale":');
  expect(editor.selectionStart).toBe(raw.lastIndexOf('"scale"'));
  change('Draft YAML', inspectionVersions[0].yaml.replace('"synthetic": true', '"synthetic": false, "synthetic": true'));
  expect(screen.getByText(/Duplicate JSON key/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Select cube' })).not.toBeInTheDocument();
 });
 it.each(['duplicate-id', 'cycle', 'missing-parent', 'unknown-field', 'infinite', 'too-many'])('rejects %s without modifying the raw draft or inventing properties', kind => {
  const doc = JSON.parse(inspectionVersions[0].yaml);
  if (kind === 'duplicate-id') doc.assets[1].id = 'table';
  if (kind === 'cycle') doc.assets[0].parent = 'cube';
  if (kind === 'missing-parent') doc.assets[1].parent = 'missing';
  if (kind === 'unknown-field') doc.runtimePrim = '/World/Cube';
  if (kind === 'infinite') doc.assets[1].pose.position[0] = 'Infinity';
  if (kind === 'too-many') doc.assets = Array.from({ length: 65 }, () => doc.assets[0]);
  const raw = JSON.stringify(doc); render(<Harness initial={raw} />);
  expect(screen.getByLabelText('Draft YAML')).toHaveValue(raw);
  expect(screen.queryByText(/Local preview checks passed/)).not.toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Read-only authored properties' })).not.toBeInTheDocument();
 });
 it('downloads the actual raw invalid draft as a local YAML blob', async () => {
  const raw = 'not: [valid\n# keep these bytes\n';
  const create = vi.fn((_blob: Blob) => 'blob:local-draft'), revoke = vi.fn();
  vi.stubGlobal('URL', Object.assign(class extends URL {}, { createObjectURL: create, revokeObjectURL: revoke }));
  const anchor = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
   expect(this.download).toBe('inspection-draft.yaml'); expect(this.href).toBe('blob:local-draft');
  });
  render(<Harness initial={raw} />); click('Download raw draft');
  const blob = create.mock.calls[0]?.[0] as unknown as Blob;
  expect(blob).toBeInstanceOf(Blob); expect(blob.type).toBe('application/yaml;charset=utf-8');
  const text = await new Promise(resolve => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.readAsText(blob); });
  expect(text).toBe(raw); expect(anchor).toHaveBeenCalledOnce(); expect(revoke).toHaveBeenCalledWith('blob:local-draft');
  expect(screen.getByLabelText('Draft YAML')).toHaveValue(raw); vi.unstubAllGlobals();
 });
 it.each(['URL.createObjectURL', 'anchor.click'])('preserves the raw draft and cleans up after %s download failure', failure => {
  const raw = 'not: [valid\n# keep these bytes\n';
  const create = vi.fn((_blob: Blob) => {
   if (failure === 'URL.createObjectURL') throw new Error('Object URL unavailable');
   return 'blob:failed-local-draft';
  }), revoke = vi.fn();
  vi.stubGlobal('URL', Object.assign(class extends URL {}, { createObjectURL: create, revokeObjectURL: revoke }));
  let clickedAnchor: HTMLAnchorElement | undefined;
  let connectedAtClick = false;
  const anchor = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
   clickedAnchor = this;
   connectedAtClick = this.isConnected;
   throw new Error('Download click unavailable');
  });
  try {
   render(<Harness initial={raw} />);
   const anchorsBefore = [...document.querySelectorAll('a')];
   click('Download raw draft');
   expect(create).toHaveBeenCalledOnce();
   expect(screen.getByRole('alert')).toHaveTextContent('Local download unavailable. Select and copy the raw draft manually; it has not been changed.');
   expect(screen.getByLabelText('Draft YAML')).toHaveValue(raw);
   expect([...document.querySelectorAll('a')]).toEqual(anchorsBefore);
   if (failure === 'URL.createObjectURL') {
    expect(anchor).not.toHaveBeenCalled(); expect(revoke).not.toHaveBeenCalled();
   } else {
    expect(anchor).toHaveBeenCalledOnce(); expect(connectedAtClick).toBe(true); expect(clickedAnchor?.isConnected).toBe(false);
    expect(revoke).toHaveBeenCalledOnce(); expect(revoke).toHaveBeenCalledWith('blob:failed-local-draft');
   }
  } finally { anchor.mockRestore(); vi.unstubAllGlobals(); }
 });
 it('keeps an exact memory-only recovery copy and restores only after reviewed consent', () => {
  const get = vi.spyOn(Storage.prototype, 'getItem'), set = vi.spyOn(Storage.prototype, 'setItem');
  render(<Harness initial={'broken: [\n'} />);
  click('Keep recovery copy'); change('Draft YAML', 'newer local bytes');
  click('Review recovery copy');
  expect(screen.getByRole('region', { name: 'Frozen recovery review' })).toHaveTextContent('broken: [');
  expect(screen.getByLabelText('Draft YAML')).toHaveValue('newer local bytes');
  expect(screen.getByRole('button', { name: 'Restore reviewed recovery copy' })).toBeDisabled();
  fireEvent.click(screen.getByLabelText('I consent to replace the current draft with this recovery copy'));
  click('Restore reviewed recovery copy'); expect(screen.getByLabelText('Draft YAML')).toHaveValue('broken: [\n');
  expect(screen.queryByRole('region', { name: 'Frozen recovery review' })).not.toBeInTheDocument();
  expect(get).not.toHaveBeenCalled(); expect(set).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
 });
 it.each(['draft', 'source'])('blocks stale recovery through %s A-B-A, with explicit discard', kind => {
  const props = { selection: inspectionVersions[0], draft: 'raw A', expanded: false, onDraft: vi.fn(), onExpandViewport: vi.fn(), onReturnToEditor: vi.fn(), onLoadExample: vi.fn(), children: <div /> };
  const { rerender } = render(<InspectCorrectWorkspace {...props} />);
  click('Keep recovery copy'); click('Review recovery copy');
  fireEvent.click(screen.getByLabelText('I consent to replace the current draft with this recovery copy'));
  rerender(<InspectCorrectWorkspace {...props} {...(kind === 'draft' ? { draft: 'raw B' } : { selection: inspectionVersions[1] })} />);
  rerender(<InspectCorrectWorkspace {...props} />);
  expect(screen.getByRole('button', { name: 'Restore reviewed recovery copy' })).toBeDisabled();
  expect(screen.getByLabelText('I consent to replace the current draft with this recovery copy')).not.toBeChecked();
  if (kind === 'source') expect(screen.getByRole('button', { name: 'Review recovery copy' })).toBeDisabled();
  expect(props.onDraft).not.toHaveBeenCalled(); click('Discard recovery copy');
  expect(screen.queryByRole('region', { name: 'Frozen recovery review' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Keep recovery copy' })).toBeEnabled();
 });
 it('explicitly clears a pose review and consent without modifying the draft or pose input', () => {
  const props = { selection: inspectionVersions[0], draft: inspectionVersions[0].yaml, onDraft: vi.fn(), expanded: false, onExpandViewport: vi.fn(), onReturnToEditor: vi.fn(), onLoadExample: vi.fn(), children: <div /> };
  render(<InspectCorrectWorkspace {...props} />);
  click('Select cube'); change('Proposed value', '0.6'); click('Review pose change');
  fireEvent.click(screen.getByLabelText('I consent to replace the draft with this reviewed pose change'));
  click('Clear pose review');
  expect(screen.queryByRole('region', { name: 'Frozen pose review' })).not.toBeInTheDocument();
  expect(screen.getByLabelText('Draft YAML')).toHaveValue(props.draft); expect(props.onDraft).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Proposed value')).toHaveValue(0.6);
  click('Review pose change');
  expect(screen.getByLabelText('I consent to replace the draft with this reviewed pose change')).not.toBeChecked();
  expect(screen.getByRole('button', { name: 'Apply reviewed pose change' })).toBeDisabled();
 });
 it('freezes a pose diff and replaces the draft only after explicit consent and apply', () => {
  render(<Harness />); click('Select cube'); change('Proposed value', '0.6');
  click('Review pose change');
  expect(screen.getByLabelText('Draft YAML')).toHaveValue(inspectionVersions[0].yaml);
  expect(screen.getByRole('region', { name: 'Frozen pose review' })).toHaveTextContent('- assets[1].pose.position[0]: 0.25');
  expect(screen.getByRole('region', { name: 'Frozen pose review' })).toHaveTextContent('+ assets[1].pose.position[0]: 0.6');
  expect(screen.getByRole('button', { name: 'Apply reviewed pose change' })).toBeDisabled();
  fireEvent.click(screen.getByLabelText('I consent to replace the draft with this reviewed pose change'));
  click('Apply reviewed pose change');
  const result = JSON.parse((screen.getByLabelText('Draft YAML') as HTMLTextAreaElement).value);
  expect(result.assets[1].pose.position).toEqual([0.6, 0, 0.8]);
  expect(result.assets[0]).toEqual(JSON.parse(inspectionVersions[0].yaml).assets[0]);
  expect(screen.getByRole('button', { name: 'Apply reviewed pose change' })).toBeDisabled();
 });
 it.each(['source', 'source-metadata', 'unbound'])('retires selected asset and pose input through %s replacement even with reused IDs', kind => {
  const props = { selection: inspectionVersions[0], draft: inspectionVersions[0].yaml, onDraft: vi.fn(), expanded: false, onExpandViewport: vi.fn(), onReturnToEditor: vi.fn(), onLoadExample: vi.fn(), children: <div /> };
  const { rerender } = render(<InspectCorrectWorkspace {...props} />);
  click('Select cube'); change('Pose field', 'rotationDegrees'); change('Pose axis', '2'); change('Proposed value', '90'); click('Review pose change');
  fireEvent.click(screen.getByLabelText('I consent to replace the draft with this reviewed pose change'));
  const replacement = kind === 'source' ? inspectionVersions[1] : kind === 'source-metadata' ? { ...props.selection, robot: 'changed option' } : null;
  rerender(<InspectCorrectWorkspace {...props} selection={replacement} />);
  expect(screen.getByRole('button', { name: 'Select cube' })).toHaveAttribute('aria-pressed', 'false');
  expect(screen.getByRole('button', { name: 'Select table' })).toHaveAttribute('aria-pressed', 'false');
  expect(screen.getByText('No authored asset selected. Select an asset to inspect or propose a pose change.')).toBeInTheDocument();
  expect(screen.queryByLabelText('Proposed value')).not.toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Read-only authored properties' })).not.toBeInTheDocument();
  click('Apply reviewed pose change'); expect(props.onDraft).not.toHaveBeenCalled();
  rerender(<InspectCorrectWorkspace {...props} />);
  expect(screen.getByRole('button', { name: 'Select cube' })).toHaveAttribute('aria-pressed', 'false');
  click('Select cube'); expect(screen.getByLabelText('Proposed value')).toHaveValue(null);
  expect(screen.getByLabelText('Pose field')).toHaveValue('position'); expect(screen.getByLabelText('Pose axis')).toHaveValue('0');
  change('Pose field', 'rotationDegrees'); change('Pose axis', '2'); change('Proposed value', '90');
  expect(screen.getByRole('region', { name: 'Frozen pose review' })).toHaveTextContent('+ assets[1].pose.rotationDegrees[2]: 90');
  expect(screen.getByLabelText('I consent to replace the draft with this reviewed pose change')).not.toBeChecked();
  expect(screen.getByRole('button', { name: 'Apply reviewed pose change' })).toBeDisabled();
  click('Apply reviewed pose change'); expect(props.onDraft).not.toHaveBeenCalled();
 });
 it.each(['removed', 'empty', 'invalid'])('retires missing asset intent through %s draft A-B-A without falling back or reviving consent', kind => {
  const props = { selection: inspectionVersions[0], draft: inspectionVersions[0].yaml, onDraft: vi.fn(), expanded: false, onExpandViewport: vi.fn(), onReturnToEditor: vi.fn(), onLoadExample: vi.fn(), children: <div /> };
  const { rerender } = render(<InspectCorrectWorkspace {...props} />);
  click('Select cube'); change('Pose field', 'rotationDegrees'); change('Pose axis', '2'); change('Proposed value', '90'); click('Review pose change');
  fireEvent.click(screen.getByLabelText('I consent to replace the draft with this reviewed pose change'));
  const doc = JSON.parse(props.draft); doc.assets = kind === 'empty' ? [] : [doc.assets[0]];
  rerender(<InspectCorrectWorkspace {...props} draft={kind === 'invalid' ? 'invalid draft' : JSON.stringify(doc)} />);
  expect(screen.queryByRole('region', { name: 'Read-only authored properties' })).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Proposed value')).not.toBeInTheDocument();
  if (kind === 'removed') expect(screen.getByRole('button', { name: 'Select table' })).toHaveAttribute('aria-pressed', 'false');
  rerender(<InspectCorrectWorkspace {...props} />);
  expect(screen.getByRole('button', { name: 'Select cube' })).toHaveAttribute('aria-pressed', 'false');
  expect(screen.getByRole('button', { name: 'Select table' })).toHaveAttribute('aria-pressed', 'false');
  click('Select cube'); expect(screen.getByLabelText('Proposed value')).toHaveValue(null);
  expect(screen.getByLabelText('Pose field')).toHaveValue('position'); expect(screen.getByLabelText('Pose axis')).toHaveValue('0');
  change('Pose field', 'rotationDegrees'); change('Pose axis', '2'); change('Proposed value', '90');
  expect(screen.getByRole('button', { name: 'Apply reviewed pose change' })).toBeDisabled();
  expect(screen.getByLabelText('I consent to replace the draft with this reviewed pose change')).not.toBeChecked();
  click('Apply reviewed pose change'); expect(props.onDraft).not.toHaveBeenCalled();
 });
 it.each(['draft', 'source', 'source-metadata', 'value', 'axis', 'field', 'asset'])('permanently invalidates retained pose consent through %s A-B-A changes', kind => {
  const props = { selection: inspectionVersions[0], draft: inspectionVersions[0].yaml, expanded: false, onDraft: vi.fn(), onExpandViewport: vi.fn(), onReturnToEditor: vi.fn(), onLoadExample: vi.fn(), children: <div>Viewport</div> };
  const { rerender } = render(<InspectCorrectWorkspace {...props} />);
  click('Select cube'); change('Proposed value', '0.6'); click('Review pose change');
  fireEvent.click(screen.getByLabelText('I consent to replace the draft with this reviewed pose change'));
  const frozen = screen.getByRole('region', { name: 'Frozen pose review' }).textContent;
  if (kind === 'draft') { rerender(<InspectCorrectWorkspace {...props} draft={props.draft + ' '} />); rerender(<InspectCorrectWorkspace {...props} />); }
  if (kind === 'source' || kind === 'source-metadata') {
   rerender(<InspectCorrectWorkspace {...props} selection={kind === 'source' ? inspectionVersions[1] : { ...props.selection, robot: 'changed option' }} />);
   rerender(<InspectCorrectWorkspace {...props} />);
  }
  if (kind === 'value') { change('Proposed value', '0.7'); change('Proposed value', '0.6'); }
  if (kind === 'axis') { change('Pose axis', '1'); change('Pose axis', '0'); }
  if (kind === 'field') { change('Pose field', 'rotationDegrees'); change('Pose field', 'position'); }
  if (kind === 'asset') { click('Select table'); click('Select cube'); }
  expect(screen.getByRole('region', { name: 'Frozen pose review' })).toHaveTextContent('+ assets[1].pose.position[0]: 0.6');
  expect(frozen).toContain('0.25');
  expect(screen.getByLabelText('I consent to replace the draft with this reviewed pose change')).not.toBeChecked();
  expect(screen.getByRole('button', { name: 'Apply reviewed pose change' })).toBeDisabled();
  expect(props.onDraft).not.toHaveBeenCalled();
 });
 it('inspects two explicitly synthetic authored versions without claiming renderer identity', () => {
  expect(inspectionVersions.map(v => v.versionId)).toEqual(['example-inspection-v1', 'example-inspection-v2']);
  expect(new Set(inspectionVersions.map(v => v.familyId)).size).toBe(1);
  for (const version of inspectionVersions) {
   const document = JSON.parse(version.yaml);
   expect(document.previewSchema).toBe('inspect-correct/v1'); expect(document.synthetic).toBe(true);
   expect(document.assets).toHaveLength(2);
   expect(document.assets[1]).toMatchObject({ id: 'cube', registry: 'preview:cube', parent: 'table', scale: [1, 1, 1] });
  }
  expect(inspectionVersions[0].yaml).not.toBe(inspectionVersions[1].yaml);
  render(<Harness />);
  click('Select cube');
  const inspector = screen.getByRole('complementary', { name: 'Authored asset inspector' });
  expect(within(inspector).getByText('preview:cube')).toBeInTheDocument();
  expect(within(inspector).getByText(/Renderer mapping unavailable/)).toBeInTheDocument();
  expect(screen.getByText(/Local preview checks passed/)).toBeInTheDocument();
  expect(screen.getAllByRole('textbox', { name: 'Draft YAML' })).toHaveLength(1);
 });
 it('preserves legacy and invalid drafts, focuses actionable findings, and bounds local validation', () => {
  render(<Harness initial={'env_name: legacy\n'} />);
  expect(screen.getByText(/Unsupported inspector/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Select cube' })).not.toBeInTheDocument();
  expect(screen.getByLabelText('Draft YAML')).toHaveValue('env_name: legacy\n');
  const doc = JSON.parse(inspectionVersions[0].yaml); doc.assets[1].scale = [0, 1, 1];
  const raw = JSON.stringify(doc); change('Draft YAML', raw);
  click('Inspect finding: assets[1].scale');
  const editor = screen.getByLabelText('Draft YAML') as HTMLTextAreaElement;
  expect(editor).toHaveFocus(); expect(editor.value).toBe(raw);
  expect(editor.selectionEnd).toBeGreaterThan(editor.selectionStart);
  change('Draft YAML', 'x'.repeat(65537)); expect(screen.getByText(/65,536 character limit/)).toBeInTheDocument();
  expect(editor.value).toHaveLength(65537);
 });
 it('offers an empty draft and explicit example CTA without remounting the viewport', () => {
  const mount = vi.fn(), unmount = vi.fn(), load = vi.fn();
  function Viewport() { useEffect(() => { mount(); return unmount; }, []); return <div data-testid="viewport">Persistent viewport</div>; }
  const props = { selection: null, draft: '', onDraft: vi.fn(), onExpandViewport: vi.fn(), onReturnToEditor: vi.fn(), onLoadExample: load };
  const { rerender } = render(<InspectCorrectWorkspace {...props} expanded={false}><Viewport /></InspectCorrectWorkspace>);
  expect(screen.getAllByRole('textbox')).toHaveLength(1);
  expect(screen.getByLabelText('Draft YAML')).toHaveValue('');
  click('Load inspection example'); expect(load).toHaveBeenCalledOnce();
  const viewport = screen.getByTestId('viewport');
  rerender(<InspectCorrectWorkspace {...props} expanded><Viewport /></InspectCorrectWorkspace>);
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.getByTestId('viewport')).toBe(viewport);
  rerender(<InspectCorrectWorkspace {...props} expanded={false}><Viewport /></InspectCorrectWorkspace>);
  expect(mount).toHaveBeenCalledOnce(); expect(unmount).not.toHaveBeenCalled();
 });
});
