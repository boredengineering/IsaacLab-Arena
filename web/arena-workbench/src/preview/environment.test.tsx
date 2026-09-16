import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useState } from 'react';
import { EnvironmentPanel } from './environment';
import type { PreviewSelection } from './types';
const selection: PreviewSelection = { familyId: 'example-c1', familyName: 'Example C1', versionId: 'example-c1-v2', version: 2, source: 'example/c1/v2/scene.yaml', yaml: 'env_name: example-c1\n', robot: 'G1', hand: 'left' };
function Harness({ source = null }: { source?: PreviewSelection | null }) {
 const [draft, setDraft] = useState(source?.yaml ?? '');
 const [prompt, setPrompt] = useState('');
 return <EnvironmentPanel selection={source} draft={draft} prompt={prompt} onDraft={setDraft} onPrompt={setPrompt} />;
}
describe('preview environment journey', () => {
 it('can delegate the sole specification editor to the cohesive workspace', () => {
  render(<EnvironmentPanel selection={null} draft="retained" prompt="" onDraft={() => {}} onPrompt={() => {}} hideDraftWorkspace />);
  expect(screen.queryByLabelText('Draft YAML')).toBeNull();
  expect(screen.getByLabelText('Scenario prompt')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('tab', { name: 'Evidence' }));
  expect(screen.getByLabelText('Inspect example retrieval state')).toBeInTheDocument();
 });
 it('keeps an available reference tab selected after applying to the external editor', () => {
  render(<EnvironmentPanel selection={null} draft="" prompt="Example intent" onDraft={() => {}} onPrompt={() => {}} hideDraftWorkspace />);
  fireEvent.click(screen.getByRole('button', { name: 'Preview generation request' }));
  fireEvent.click(screen.getByRole('button', { name: 'Show example candidate' }));
  fireEvent.click(screen.getByRole('button', { name: 'Review example candidate' }));
  fireEvent.click(screen.getByRole('button', { name: 'Apply example to draft' }));
  expect(screen.getByRole('tab', { name: 'Evidence' })).toHaveAttribute('aria-selected', 'true');
 });
 it('captures the chosen robot constraint in the frozen summary', () => {
  render(<Harness />);
  fireEvent.change(screen.getByLabelText('Scenario prompt'), { target: { value: 'A constrained task' } });
  fireEvent.change(screen.getByLabelText('Robot constraint'), { target: { value: 'G1 — left-hand profile' } });
  fireEvent.click(screen.getByRole('button', { name: 'Preview generation request' }));
  expect(screen.getByTestId('request-summary')).toHaveTextContent('G1 — left-hand profile');
 });
 it('starts prompt-first and validates before a local request preview', () => {
  render(<Harness />);
  expect(screen.getByLabelText('New environment')).toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: 'Preview generation request' }));
  expect(screen.getByRole('alert')).toHaveTextContent('Enter a prompt');
  fireEvent.change(screen.getByLabelText('Scenario prompt'), { target: { value: 'Move the banana to the large plate.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Preview generation request' }));
  expect(screen.getByTestId('request-summary')).toHaveTextContent('No base document');
  expect(fetch).not.toHaveBeenCalled();
 });
 it('freezes a request and applies a labelled example only after explicit review', () => {
  render(<Harness />);
  fireEvent.change(screen.getByLabelText('Scenario prompt'), { target: { value: 'Original prompt' } });
  fireEvent.click(screen.getByRole('button', { name: 'Preview generation request' }));
  fireEvent.change(screen.getByLabelText('Scenario prompt'), { target: { value: 'Later prompt' } });
  expect(screen.getByTestId('request-summary')).toHaveTextContent('Original prompt');
  expect(screen.getByTestId('request-summary')).not.toHaveTextContent('Later prompt');
  fireEvent.click(screen.getByRole('button', { name: 'Show example candidate' }));
  expect(screen.getByLabelText('Draft YAML')).toHaveValue('');
  fireEvent.click(screen.getByRole('button', { name: 'Review example candidate' }));
  fireEvent.click(screen.getByRole('button', { name: 'Apply example to draft' }));
  expect((screen.getByLabelText('Draft YAML') as HTMLTextAreaElement).value).toContain('example-a2');
  expect(fetch).not.toHaveBeenCalled();
 });
 it('refine binds an exact selected version but new never inherits it', () => {
  render(<Harness source={selection} />);
  fireEvent.click(screen.getByLabelText('Refine selected version'));
  fireEvent.change(screen.getByLabelText('Refinement feedback'), { target: { value: 'Move object left' } });
  fireEvent.click(screen.getByRole('button', { name: 'Preview generation request' }));
  expect(screen.getByTestId('request-summary')).toHaveTextContent('example-c1-v2');
  fireEvent.click(screen.getByLabelText('New environment'));
  fireEvent.change(screen.getByLabelText('Scenario prompt'), { target: { value: 'A new task' } });
  fireEvent.click(screen.getByRole('button', { name: 'Preview generation request' }));
  expect(screen.getByTestId('request-summary')).toHaveTextContent('No base document');
 });
 it('blocks refinement without a source and never claims a real result', () => {
  render(<Harness />);
  expect(screen.getByLabelText('Refine selected version')).toBeDisabled();
  expect(screen.getByText(/No model is called/)).toBeInTheDocument();
 });
});
