import { existsSync, readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { describe, it, expect, afterEach, vi } from 'vitest';
import { cleanup, render, screen, fireEvent, within } from '@testing-library/react';
afterEach(cleanup);

it('searches exact entries, inspects restrictions and pages bounded rows', async () => {
  expect(existsSync('src/preview/coverage.tsx')).toBe(true);
  const modulePath = './coverage';
  const { CoveragePanel } = await import(modulePath);
  const navigate = vi.fn();
  render(<CoveragePanel onNavigate={navigate} />);
  expect(screen.getAllByTestId('coverage-row')).toHaveLength(20);
  const first = screen.getAllByTestId('coverage-row')[0].textContent;
  fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
  expect(screen.getAllByTestId('coverage-row')[0].textContent).not.toBe(first);
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search coverage' }), { target: { value: 'field.gr00t_yaml.denoising_steps' } });
  expect(screen.getAllByTestId('coverage-row')).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Inspect field.gr00t_yaml.denoising_steps' }));
  const inspector = screen.getByRole('region', { name: 'Entry inspector' });
  expect(within(inspector).getByText('unresolved audit')).toBeInTheDocument();
  expect(within(inspector).queryByRole('textbox')).not.toBeInTheDocument();
  expect(within(inspector).getByText(/No typed field control claimed/)).toBeInTheDocument();
  fireEvent.click(within(inspector).getByRole('button', { name: /Open Build/ }));
  expect(navigate).toHaveBeenCalledWith('build');
});

it('offers substantive local schema and catalogue references without inventing live metadata', async () => {
  const modulePath = './coverage';
  const { CoveragePanel } = await import(modulePath);
  render(<CoveragePanel onNavigate={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'C01 Schema reference' }));
  expect(screen.getByRole('searchbox', { name: 'Search reference fields' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Inspect reference target_node_id' }));
  expect(screen.getByText('example-node-1')).toBeInTheDocument();
  expect(screen.getByText(/required_no_default/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'C02 Catalogue reference' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Catalogue kind' }), { target: { value: 'relation' } });
  expect(screen.getByText('example-relation-constraint')).toBeInTheDocument();
  expect(screen.getByText(/Selecting a constraint does not select a base/)).toBeInTheDocument();
});

it('keeps source deltas outside canonical IDs and validates every screen mapping and blocked disposition', async () => {
  const modulePath = './coverage';
  const { capabilityScreens, representation } = await import(modulePath);
  const data = JSON.parse(readFileSync('src/preview/coverage-data.json', 'utf8'));
  expect(Object.keys(capabilityScreens).sort()).toEqual(data.capability_ids);
  expect(data.source_delta).toHaveLength(12);
  expect(new Set(data.source_delta.map((d: { option: string }) => d.option)).size).toBe(12);
  for (const delta of data.source_delta) { expect(delta.canonical_ledger_id).toBeNull(); expect(delta.option).toMatch(/^--managed_/); }
  expect(data.remaining_audit_gaps.map((g: { id: string }) => g.id)).toEqual(['G01', 'G02', 'G03', 'G04', 'G05']);
  for (const entry of data.entries) {
    for (const cap of entry.capability_ids) expect(capabilityScreens[cap]).toBeDefined();
    if (entry.disposition.startsWith('blocked')) expect(representation(entry)).not.toBe('planned field representation');
  }
});

it('filters unresolved audits and never renders editable controls for blocked fields', async () => {
  const modulePath = './coverage';
  const { CoveragePanel } = await import(modulePath);
  render(<CoveragePanel onNavigate={vi.fn()} />);
  fireEvent.change(screen.getByRole('combobox', { name: 'Representation' }), { target: { value: 'unresolved audit' } });
  expect(screen.getAllByTestId('coverage-row')).toHaveLength(5);
  fireEvent.change(screen.getByRole('combobox', { name: 'Representation' }), { target: { value: '' } });
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search coverage' }), { target: { value: 'cli.generation.list_variations' } });
  fireEvent.click(screen.getByRole('button', { name: 'Inspect cli.generation.list_variations' }));
  const inspector = screen.getByRole('region', { name: 'Entry inspector' });
  expect(within(inspector).getByText('blocked_existing_noop')).toBeInTheDocument();
  expect(within(inspector).queryByRole('textbox')).not.toBeInTheDocument();
  expect(within(inspector).queryByRole('spinbutton')).not.toBeInTheDocument();
  expect(within(inspector).queryByRole('combobox')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Audit gaps G01–G05' }));
  for (const id of ['G01', 'G02', 'G03', 'G04', 'G05']) expect(screen.getByRole('heading', { name: new RegExp(`^${id}`) })).toBeInTheDocument();
});

it('pages every historical ID exactly once', async () => {
  const modulePath = './coverage';
  const { CoveragePanel } = await import(modulePath);
  render(<CoveragePanel onNavigate={vi.fn()} />);
  const ids: string[] = [];
  for (;;) {
    const rows = screen.getAllByTestId('coverage-row');
    expect(rows.length).toBeLessThanOrEqual(20);
    ids.push(...rows.map(row => within(row).getByRole('button').textContent ?? ''));
    const next = screen.getByRole('button', { name: 'Next page' });
    if (next.hasAttribute('disabled')) break;
    fireEvent.click(next);
  }
  expect(ids).toHaveLength(394);
  expect(new Set(ids).size).toBe(394);
});

describe('historical coverage integrity', () => {
  it('preserves all exact historical IDs and per-entry capability sets', () => {
    const path = 'src/preview/coverage-data.json';
    expect(existsSync(path)).toBe(true);
    const data = JSON.parse(readFileSync(path, 'utf8'));
    expect(data.entries).toHaveLength(394);
    const exactKeys = ['id', 'source_refs', 'profile', 'default', 'precedence', 'capability_ids', 'disposition'];
    const exactMetadata = data.entries.map((entry: Record<string, unknown>) => Object.fromEntries(exactKeys.map(key => [key, entry[key]])));
    expect(createHash('sha256').update(JSON.stringify(exactMetadata)).digest('hex')).toBe('9f7306f4f88087e5ea7f8a28bc1d8e7ea348d9ad39443973e500458f6f321894');
    const inventoryIds = data.source_inventories.flatMap((inventory: { enumerated_source_ids: string[] }) => inventory.enumerated_source_ids);
    expect(inventoryIds).toHaveLength(394);
    expect(new Set(inventoryIds).size).toBe(394);
    const ids = data.entries.map((e: { id: string }) => e.id).sort();
    expect(new Set(ids).size).toBe(394);
    expect(createHash('sha256').update(ids.join('\n')).digest('hex')).toBe('cf07033975153c23f396e6b9ad62b2e2b07024b1c935de22f4bb7940e353a40f');
    const sets = Object.fromEntries([...data.entries].sort((a, b) => a.id.localeCompare(b.id)).map(e => [e.id, [...e.capability_ids].sort()]));
    expect(createHash('sha256').update(JSON.stringify(sets)).digest('hex')).toBe('f2e20c42518538b65ab38a48a1b121c16e2fa548cbbacbb1671c38ec0db75065');
  });
});
