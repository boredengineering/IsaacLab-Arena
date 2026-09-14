import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { PropertyTree } from './property-tree';

it('inspects nested properties on demand and displays hostile strings as text', () => {
  render(<PropertyTree value={{ nested: { '<img src=x onerror=alert(1)>': '[truncated]' }, nil: null }} />);
  expect(screen.queryByText('[truncated]')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Expand nested' }));
  expect(screen.getByText('[truncated]')).toBeInTheDocument();
  expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
  expect(document.querySelector('img')).toBeNull();
  expect(screen.getByText('null')).toBeInTheDocument();
});

it('accepts non-object truncation sentinels without inventing properties', () => {
  render(<PropertyTree value="[truncated]" />);
  expect(screen.getByText('[truncated]')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Expand/ })).not.toBeInTheDocument();
});

it('paginates wide objects instead of eagerly rendering every child', () => {
  render(<PropertyTree value={Object.fromEntries(Array.from({ length: 250 }, (_, i) => [`key${i}`, i]))} />);
  expect(screen.getByText('key0')).toBeInTheDocument();
  expect(screen.queryByText('key100')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Next properties page for Properties' }));
  expect(screen.getByText('key100')).toBeInTheDocument();
  expect(screen.queryByText('key0')).not.toBeInTheDocument();
});

it('segments long scalar values and does not leave an unbounded text node', () => {
  render(<PropertyTree value={'a'.repeat(1024) + 'last segment'} />);
  expect(screen.queryByText(/last segment/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Next text segment for Properties' }));
  expect(screen.getByText('last segment')).toBeInTheDocument();
});

it('bounds the total expanded rows while retaining collapse controls', () => {
  const value = Object.fromEntries(Array.from({ length: 6 }, (_, i) => [`group${i}`, Array.from({ length: 100 }, (_, j) => j)]));
  render(<PropertyTree value={value} />);
  for (let i = 0; i < 5; i++) fireEvent.click(screen.getByRole('button', { name: `Expand group${i}` }));
  expect(document.querySelectorAll('[data-property-row]').length).toBeLessThanOrEqual(500);
  expect(screen.getByText(/Property display limit/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Collapse all properties' }));
  expect(document.querySelectorAll('[data-property-row]').length).toBeLessThan(10);
});

it('preserves scalar type distinctions and reveals long colliding property names in bounded segments', () => {
  const prefix = 'k'.repeat(1100);
  render(<PropertyTree value={{ [prefix + 'first']: null, [prefix + 'second']: 'null', number: 12, text: '12' }} />);
  expect(document.querySelectorAll('[data-value-type="string"]')).toHaveLength(2);
  expect(document.querySelectorAll('[data-value-type="number"]')).toHaveLength(1);
  expect([...document.querySelectorAll('[data-property-row]')].filter(row => row.getAttribute('data-value-type') === 'null')).toHaveLength(1);
  const names = screen.getAllByRole('button', { name: /Inspect full property name/ });
  expect(names).toHaveLength(2);
  fireEvent.click(names[1]);
  expect(screen.queryByText(prefix + 'second')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Next text segment for property name/ }));
  expect(screen.getByText(prefix.slice(1024) + 'second')).toBeInTheDocument();
});
