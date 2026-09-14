import { act, fireEvent, render, screen } from '@testing-library/react';
import { useEffect } from 'react';
import { expect, it, vi } from 'vitest';
import type { GraphRendererProps } from './renderer-contracts';
const deferred = vi.hoisted(() => {
  let resolve!: (module: { default: (props: GraphRendererProps) => React.ReactNode }) => void;
  const promise = new Promise<{ default: (props: GraphRendererProps) => React.ReactNode }>(done => { resolve = done; });
  return { promise, resolve, mounts: vi.fn(), orbit: vi.fn() };
});
vi.mock('./graph-2d', () => ({ default: () => <p>Mock 2D</p> }));
vi.mock('./graph-3d', () => deferred.promise);
import GraphExplorer from './graph-explorer';
it('leaves late 3D module resolution inert after mode, scope and withheld-data transitions', async () => {
  const graph = (id: string) => ({ nodes: [{ id, label: id, role: 'object', properties: {} }], edges: [] });
  const { rerender } = render(<GraphExplorer graph={graph('old')} scopeKey="old" revisionKey="1" label="Loading" sourceKind="authored" />);
  fireEvent.click(screen.getByRole('tab', { name: '3D' }));
  expect(screen.getByText(/Loading 3D renderer/)).toBeTruthy();
  fireEvent.click(screen.getByRole('tab', { name: 'Table' }));
  rerender(<GraphExplorer graph={null} scopeKey="new" revisionKey="2" label="Loading" sourceKind="authored" />);
  await act(async () => { deferred.resolve({ default: props => { useEffect(() => { props.onReady({ fit: vi.fn(), zoom: vi.fn(), pan: vi.fn(), orbit: deferred.orbit, reset: vi.fn(), setFrozen: vi.fn(), setPinned: vi.fn(), unpinAll: vi.fn(), moveNode: vi.fn(), nudgeNode: vi.fn(), getSnapshot: () => props.snapshot }); return () => props.onReady(null); }, [props.onReady]); deferred.mounts(props.scopeKey); return <p>3D current node: {props.graph.nodes[0]?.id}</p>; } }); await deferred.promise; });
  expect(deferred.mounts).not.toHaveBeenCalled();
  rerender(<GraphExplorer graph={graph('new')} scopeKey="new" revisionKey="2" label="Loading" sourceKind="authored" />);
  fireEvent.click(screen.getByRole('tab', { name: '3D' }));
  expect(await screen.findByText('3D current node: new')).toBeTruthy();
  expect(deferred.mounts).toHaveBeenCalledWith('new');
  expect(deferred.mounts).not.toHaveBeenCalledWith('old');
  fireEvent.click(screen.getByRole('button', { name: 'Orbit up' }));
  expect(deferred.orbit).toHaveBeenCalledWith(0, 10 * Math.PI / 180);
});
