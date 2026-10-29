import { act, fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
const deferred = vi.hoisted(() => {
  let reject!: (error: Error) => void;
  const promise = new Promise<never>((_resolve, fail) => { reject = fail; });
  return { promise, reject };
});
vi.mock('./graph-2d', () => ({ default: () => <p>Mock 2D</p> }));
vi.mock('./graph-3d', () => deferred.promise);
import GraphExplorer from './graph-explorer';
it('contains a delayed import rejection without losing Table or local selection', async () => {
  const log = vi.spyOn(console, 'error').mockImplementation(() => {});
  const graph = { nodes: [{ id: 'a', label: 'Alpha', role: 'object', properties: {} }], edges: [] };
  render(<GraphExplorer graph={graph} scopeKey="reject" revisionKey="1" label="Rejected module" sourceKind="persisted" />);
  fireEvent.click(screen.getByRole('tab', { name: 'Table' }));
  fireEvent.click(screen.getByRole('button', { name: 'Inspect node a' }));
  fireEvent.click(screen.getByRole('tab', { name: '3D' }));
  fireEvent.click(screen.getByRole('tab', { name: 'Table' }));
  await act(async () => { deferred.reject(new Error('Chunk unavailable')); await deferred.promise.catch(() => {}); });
  expect(screen.queryByRole('alert')).toBeNull();
  expect(screen.getByText('Node: Alpha')).toBeTruthy();
  fireEvent.click(screen.getByRole('tab', { name: '3D' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Preserve unsaved work');
  fireEvent.click(screen.getByRole('tab', { name: 'Table' }));
  expect(screen.getByRole('table')).toBeTruthy();
  expect(screen.getByText('Node: Alpha')).toBeTruthy();
  log.mockRestore();
});
