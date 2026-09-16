import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { PreviewApp } from './preview-app';

it('keeps account layouts and the theme switch in the global top bar without accepting credentials', () => {
 render(<PreviewApp />);
 const top = screen.getByRole('banner', { name: 'Preview top bar' });
 expect(within(top).getByText('Preview v7')).toBeInTheDocument();
 expect(within(top).getByRole('img', { name: 'Cybernetic-Physics' })).toBeInTheDocument();
 expect(screen.queryByText('ARENA', { exact: true })).toBeNull();
 expect(screen.getByText('Typography licenses')).toBeInTheDocument();
 const themeSwitch = within(top).getByRole('switch', { name: 'Dark mode' });
 expect(themeSwitch).toHaveAttribute('aria-checked', 'true');
 expect(within(themeSwitch).getByText('Dark')).toBeInTheDocument();
 fireEvent.change(screen.getByLabelText('Draft YAML'), { target: { value: 'preserve through theme switch' } });
 fireEvent.click(themeSwitch);
 expect(document.documentElement.dataset.theme).toBe('light');
 expect(themeSwitch).toHaveAttribute('aria-checked', 'false');
 expect(within(themeSwitch).getByText('Light')).toBeInTheDocument();
 expect(screen.getByLabelText('Draft YAML')).toHaveValue('preserve through theme switch');
 for (const [button, title] of [['Login', 'Login preview'], ['Sign up', 'Sign up preview']]) {
  fireEvent.click(within(top).getByRole('button', { name: button }));
  const dialog = screen.getByRole('dialog', { name: title });
  expect(within(dialog).getByText(/No credentials are accepted/)).toBeInTheDocument();
  expect(dialog.querySelector('form')).toBeNull();
  for (const input of dialog.querySelectorAll('input')) expect(input).toBeDisabled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close account preview' }));
 }
 expect(fetch).not.toHaveBeenCalled();
});

it('collapses and expands left navigation without losing the draft or its navigation controls', () => {
 render(<PreviewApp />);
 fireEvent.change(screen.getByLabelText('Draft YAML'), { target: { value: 'example retained draft' } });
 fireEvent.change(screen.getByLabelText('Scenario prompt'), { target: { value: 'Keep this intent' } });
 const sidebar = screen.getByRole('complementary', { name: 'Workspace sidebar' });
 const collapse = within(sidebar).getByRole('button', { name: 'Collapse left sidebar' });
 expect(within(screen.getByRole('banner', { name: 'Preview top bar' })).queryByRole('button', { name: /left sidebar/ })).toBeNull();
 expect(collapse).toHaveAttribute('aria-expanded', 'true');
 fireEvent.click(collapse);
 expect(screen.getByRole('button', { name: 'Expand left sidebar' })).toHaveAttribute('aria-expanded', 'false');
 const nav = screen.getByRole('navigation', { name: 'Preview navigation' });
 fireEvent.click(within(nav).getByRole('button', { name: 'Library' }));
 fireEvent.click(within(nav).getByRole('button', { name: 'Environment' }));
 fireEvent.click(screen.getByRole('button', { name: 'Expand left sidebar' }));
 fireEvent.keyDown(within(nav).getByRole('button', { name: 'Environment' }), { key: 'Escape' });
 expect(within(sidebar).getByRole('button', { name: 'Expand left sidebar' })).toHaveFocus();
 expect(screen.getByLabelText('Draft YAML')).toHaveValue('example retained draft');
 expect(screen.getByLabelText('Scenario prompt')).toHaveValue('Keep this intent');
 expect(fetch).not.toHaveBeenCalled();
});

it('restores the explicit desktop sidebar preference after a narrow viewport', () => {
 let resize: (event: { matches: boolean }) => void = () => {};
 vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: (_: string, listener: typeof resize) => { resize = listener; }, removeEventListener: vi.fn() }));
 try {
  render(<PreviewApp />);
  expect(screen.getByRole('button', { name: 'Collapse left sidebar' })).toBeInTheDocument();
  act(() => resize({ matches: true }));
  expect(screen.getByRole('button', { name: 'Expand left sidebar' })).toBeInTheDocument();
  act(() => resize({ matches: false }));
  fireEvent.click(screen.getByRole('button', { name: 'Collapse left sidebar' }));
  act(() => resize({ matches: true }));
  fireEvent.click(screen.getByRole('button', { name: 'Expand left sidebar' }));
  act(() => resize({ matches: false }));
  expect(screen.getByRole('button', { name: 'Expand left sidebar' })).toBeInTheDocument();
 } finally { vi.unstubAllGlobals(); }
});

function openC1() {
 fireEvent.change(screen.getByLabelText('Environment family'), { target: { value: 'example-c1-g1-tabletop' } });
 fireEvent.click(screen.getByRole('button', { name: 'Open selected version' }));
 fireEvent.click(screen.getByLabelText('Refine selected version'));
 fireEvent.change(screen.getByLabelText('Refinement feedback'), { target: { value: 'Keep feedback until explicit reset' } });
}

it('exposes query and operational jobs independently of editor and publication actions', () => {
 render(<PreviewApp />);
 fireEvent.change(screen.getByLabelText('Draft YAML'), { target: { value: 'preserved editor draft' } });
 const nav = screen.getByRole('navigation', { name: 'Preview navigation' });
 for (const name of ['Neo4j query', 'Jobs & diagnostics']) {
  fireEvent.click(within(nav).getByRole('button', { name }));
  expect(screen.getByRole('region', { name: `${name} workspace` })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Review version save' })).toBeNull();
  expect(screen.queryByRole('region', { name: 'Workflow source binding' })).toBeNull();
  expect(screen.queryByRole('combobox', { name: 'Publication operation' })).toBeNull();
 }
 fireEvent.click(within(nav).getByRole('button', { name: 'Environment' }));
 expect(screen.getByLabelText('Draft YAML')).toHaveValue('preserved editor draft');
 expect(fetch).not.toHaveBeenCalled();
});

it('opens the asset and scene visualizer without replacing the editor draft', () => {
 render(<PreviewApp />);
 fireEvent.change(screen.getByLabelText('Draft YAML'), { target: { value: 'retained visualization source' } });
 const nav = screen.getByRole('navigation', { name: 'Preview navigation' });
 const viewer = document.querySelector('.preview-visualizer');
 expect(viewer).not.toBeNull();
 fireEvent.click(within(nav).getByRole('button', { name: 'Assets & scene' }));
 expect(document.querySelector('.preview-visualizer')).toBe(viewer);
 expect(screen.getByRole('region', { name: 'Assets & scene workspace' })).toBeInTheDocument();
 expect(screen.queryByRole('region', { name: 'Workflow source binding' })).toBeNull();
 fireEvent.click(within(nav).getByRole('button', { name: 'Environment' }));
 expect(screen.getByLabelText('Draft YAML')).toHaveValue('retained visualization source');
 expect(document.querySelectorAll('.preview-visualizer')).toHaveLength(1);
 expect(document.querySelector('.preview-visualizer')).toBe(viewer);
 expect(fetch).not.toHaveBeenCalled();
});

it('links activity to the exact example job without changing the draft or repairing unavailable observation', () => {
 render(<PreviewApp />);
 fireEvent.change(screen.getByLabelText('Draft YAML'), { target: { value: 'keep activity draft' } });
 fireEvent.click(screen.getByRole('button', { name: 'Activity examples' }));
 const activity = screen.getByRole('region', { name: 'Activity preview' });
 fireEvent.click(within(activity).getByRole('button', { name: 'Show example jobs' }));
 fireEvent.click(within(activity).getByRole('button', { name: 'Inspect example-blocked' }));
 expect(screen.getByRole('region', { name: 'Exact example job inspector' })).toHaveTextContent('example-blocked');
 fireEvent.change(screen.getByLabelText('Snapshot example state'), { target: { value: 'unavailable' } });
 fireEvent.click(screen.getByRole('button', { name: 'Activity examples' }));
 fireEvent.click(within(screen.getByRole('region', { name: 'Activity preview' })).getByRole('button', { name: 'Inspect example-blocked' }));
 expect(screen.getByLabelText('Requested job navigation')).toHaveTextContent('details unavailable');
 expect(screen.queryByRole('region', { name: 'Exact example job inspector' })).toBeNull();
 fireEvent.click(within(screen.getByRole('navigation', { name: 'Preview navigation' })).getByRole('button', { name: 'Environment' }));
 expect(screen.getByLabelText('Draft YAML')).toHaveValue('keep activity draft');
 expect(fetch).not.toHaveBeenCalled();
});

it('reviews an authored change beside the retained viewport and protects unsaved example loading', () => {
 render(<PreviewApp />);
 fireEvent.change(screen.getByLabelText('Draft YAML'), { target: { value: 'unsaved text' } });
 fireEvent.click(screen.getByRole('button', { name: 'Load inspection example' }));
 fireEvent.click(screen.getByRole('button', { name: 'Keep current draft' }));
 expect(screen.getByLabelText('Draft YAML')).toHaveValue('unsaved text');
 fireEvent.click(screen.getByRole('button', { name: 'Load inspection example' }));
 fireEvent.click(screen.getByRole('button', { name: 'Discard edits and continue' }));
 expect(screen.getByTestId('selection-context')).toHaveTextContent('example-inspection-v1');
 fireEvent.click(screen.getByRole('button', { name: 'Select cube' }));
 fireEvent.change(screen.getByLabelText('Proposed value'), { target: { value: '0.5' } });
 fireEvent.click(screen.getByRole('button', { name: 'Review pose change' }));
 const draft = screen.getByLabelText('Draft YAML') as HTMLTextAreaElement;
 expect(JSON.parse(draft.value).assets[1].pose.position[0]).toBe(0.25);
 fireEvent.click(screen.getByLabelText('I consent to replace the draft with this reviewed pose change'));
 fireEvent.click(screen.getByRole('button', { name: 'Apply reviewed pose change' }));
 expect(JSON.parse(draft.value).assets[1].pose.position[0]).toBe(0.5);
 const viewer = document.querySelector('.preview-visualizer');
 fireEvent.click(screen.getByRole('button', { name: 'Expand viewport' }));
 expect(draft).not.toBeVisible();
 fireEvent.click(screen.getByRole('button', { name: 'Return to editor' }));
 expect(draft).toBeVisible();
 expect(document.querySelector('.preview-visualizer')).toBe(viewer);
 const nav = screen.getByRole('navigation', { name: 'Preview navigation' });
 fireEvent.click(within(nav).getByRole('button', { name: 'Library' }));
 expect(screen.getByRole('region', { name: 'Recent opens' })).toHaveTextContent('example-inspection-v1');
 fireEvent.click(within(nav).getByRole('button', { name: 'Environment' }));
 expect(screen.getByRole('button', { name: 'Select cube' })).toHaveAttribute('aria-pressed', 'true');
 expect(JSON.parse(draft.value).assets[1].pose.position[0]).toBe(0.5);
});

it('reset confirms pending refinement inputs then returns to a clean New composer', () => {
 render(<PreviewApp />); openC1();
 fireEvent.click(screen.getByRole('button', { name: 'Preview generation request' }));
 fireEvent.click(screen.getByRole('button', { name: 'Show example candidate' }));
 fireEvent.click(screen.getByRole('button', { name: 'Start new draft' }));
 fireEvent.click(screen.getByRole('button', { name: 'Keep current draft' }));
 expect(screen.getByLabelText('Refinement feedback')).toHaveValue('Keep feedback until explicit reset');
 fireEvent.click(screen.getByRole('button', { name: 'Start new draft' }));
 fireEvent.click(screen.getByRole('button', { name: 'Discard edits and continue' }));
 expect(screen.getByLabelText('New environment')).toBeChecked();
 expect(screen.getByLabelText('Scenario prompt')).toHaveValue('');
 expect(screen.queryByTestId('request-summary')).toBeNull();
 expect(screen.queryByText('Example candidate · not generated')).toBeNull();
});

it('ordinary navigation preserves refinement feedback but explicit source replacement clears it', () => {
 render(<PreviewApp />); openC1();
 fireEvent.click(screen.getByRole('button', { name: 'Preview generation request' }));
 fireEvent.click(screen.getByRole('button', { name: 'Show example candidate' }));
 const nav = screen.getByRole('navigation', { name: 'Preview navigation' });
 fireEvent.click(within(nav).getByRole('button', { name: 'Library' }));
 fireEvent.click(within(nav).getByRole('button', { name: 'Environment' }));
 expect(screen.getByLabelText('Refinement feedback')).toHaveValue('Keep feedback until explicit reset');
 fireEvent.change(screen.getByLabelText('Environment version'), { target: { value: 'example-c1-g1-tabletop-v2' } });
 fireEvent.click(screen.getByRole('button', { name: 'Open selected version' }));
 fireEvent.click(screen.getByRole('button', { name: 'Discard edits and continue' }));
 fireEvent.click(screen.getByLabelText('Refine selected version'));
 expect(screen.getByLabelText('Refinement feedback')).toHaveValue('');
 expect(screen.queryByTestId('request-summary')).toBeNull();
 expect(screen.queryByText('Example candidate · not generated')).toBeNull();
});

it('shows the whole research navigation without API connections and retains the draft', () => {
 render(<PreviewApp />);
 const nav = screen.getByRole('navigation', { name: 'Preview navigation' });
 for (const name of ['Environment', 'Library', 'Build & evaluate', 'Improve', 'Experiments', 'Runs & evidence', 'Research graph', 'Settings & readiness', 'Coverage & reference']) expect(within(nav).getByRole('button', { name })).toBeInTheDocument();
 fireEvent.change(screen.getByLabelText('Scenario prompt'), { target: { value: 'Keep this prompt' } });
 fireEvent.change(screen.getByLabelText('Draft YAML'), { target: { value: 'env_name: example-edited' } });
 fireEvent.click(within(nav).getByRole('button', { name: 'Library' }));
 fireEvent.click(within(nav).getByRole('button', { name: 'Environment' }));
 expect(screen.getByLabelText('Scenario prompt')).toHaveValue('Keep this prompt');
 expect(screen.getByLabelText('Draft YAML')).toHaveValue('env_name: example-edited');
 expect(fetch).not.toHaveBeenCalled();
});

it('previews a saved version only after confirmation and keeps the immutable local snapshot', () => {
 render(<PreviewApp />);
 fireEvent.change(screen.getByLabelText('Draft YAML'), { target: { value: 'env_name: example-proposal' } });
 fireEvent.click(screen.getByRole('button', { name: 'Review version save' }));
 expect(screen.getByRole('dialog', { name: 'Review example version save' })).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', { name: 'Create local example version' }));
 expect(screen.getByTestId('selection-context')).toHaveTextContent('example-local-1');
 fireEvent.change(screen.getByLabelText('Draft YAML'), { target: { value: 'changed draft' } });
 expect(screen.getByTestId('selection-context')).toHaveTextContent('Draft differs from selected version');
 expect(fetch).not.toHaveBeenCalled();
});
