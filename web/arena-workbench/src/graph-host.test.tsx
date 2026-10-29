import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { GraphHost, parseGraphRenderer } from './graph-host';

const fixture = vi.hoisted(() => ({ fail: false }));
beforeEach(() => { fixture.fail = false; });
vi.mock('./graph-explorer/graph-explorer', () => ({ default: ({ graph, visible, scopeKey }: { graph: unknown; visible: boolean; scopeKey: string }) => {
  if (fixture.fail) throw new Error('Synthetic renderer failure');
  return <div data-testid="explorer-controller" data-visible={visible} data-valid={graph !== null}>{scopeKey}</div>;
} }));
const graph = { nodes: [{ id: 'one', label: 'One', role: 'object', properties: {} }], edges: [] };
const props = { graph, scopeKey: 'session:document', revisionKey: 'revision', label: 'Test graph', sourceKind: 'authored' as const };

it('defaults to legacy unless an explicit valid explorer choice is made', () => {
  expect(parseGraphRenderer(undefined)).toBe('legacy');
  expect(parseGraphRenderer('explorer')).toBe('explorer');
  expect(parseGraphRenderer('legacy')).toBe('legacy');
  expect(parseGraphRenderer(['explorer'])).toBe('legacy');
  const change = vi.fn();
  render(<GraphHost {...props} renderer="legacy" onRendererChange={change} />);
  expect(screen.getByRole('button', { name: 'Inspect One' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Try graph explorer' }));
  expect(change).toHaveBeenCalledWith('explorer');
});

it('keeps the explorer controller mounted while withholding invalid or hidden graph content', async () => {
  const view = render(<GraphHost {...props} renderer="explorer" onRendererChange={() => {}} />);
  const controller = await screen.findByTestId('explorer-controller');
  view.rerender(<GraphHost {...props} graph={null} renderer="explorer" onRendererChange={() => {}} />);
  expect(screen.getByTestId('explorer-controller')).toBe(controller);
  expect(controller).toHaveAttribute('data-valid', 'false');
  view.rerender(<GraphHost {...props} visible={false} renderer="explorer" onRendererChange={() => {}} />);
  expect(screen.getByTestId('explorer-controller')).toBe(controller);
  expect(controller).toHaveAttribute('data-visible', 'false');
  view.rerender(<GraphHost {...props} scopeKey="new-session:document" renderer="explorer" onRendererChange={() => {}} />);
  await waitFor(() => expect(screen.getByTestId('explorer-controller')).not.toBe(controller));
});

it('returns to legacy without changing the graph input', async () => {
  const change = vi.fn();
  const before = JSON.stringify(graph);
  const view = render(<GraphHost {...props} renderer="explorer" onRendererChange={change} />);
  await screen.findByTestId('explorer-controller');
  fireEvent.click(screen.getByRole('button', { name: 'Use legacy graph' }));
  expect(change).toHaveBeenCalledWith('legacy');
  view.rerender(<GraphHost {...props} renderer="legacy" onRendererChange={change} />);
  expect(screen.queryByTestId('explorer-controller')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Inspect One' })).toBeInTheDocument();
  expect(JSON.stringify(graph)).toBe(before);
});

it('keeps rollback outside failure boundaries and hides explorer errors in raw-row mode', async () => {
  fixture.fail = true;
  const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  try {
    const change = vi.fn();
    const view = render(<GraphHost {...props} renderer="explorer" onRendererChange={change} />);
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'Use legacy graph' }));
    expect(change).toHaveBeenCalledWith('legacy');
    view.rerender(<GraphHost {...props} visible={false} renderer="explorer" onRendererChange={change} />);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  } finally { consoleError.mockRestore(); }
});
