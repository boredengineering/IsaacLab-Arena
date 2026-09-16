import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { exampleJobSummaries, JobsDiagnosticsPreview } from './jobs-diagnostics';

afterEach(() => { cleanup(); vi.useRealTimers(); });
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));
const change = (name: string, value: string) => fireEvent.change(screen.getByLabelText(name), { target: { value } });
const selectJob = (id: string) => click(`Inspect ${id}`);
const inspector = () => within(screen.getByRole('region', { name: 'Exact example job inspector' }));

const tab = (name: string) => fireEvent.click(screen.getByRole('tab', { name }));
const enableDiagnostics = () => {
  tab('Developer diagnostics');
  change('Diagnostic capability example', 'available');
  fireEvent.click(screen.getByLabelText('Consent to local diagnostic review only'));
};

describe('developer diagnostics reviews', () => {
  it('supports keyboard tabs without discarding local form state', () => {
    render(<JobsDiagnosticsPreview />);
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Job journal' }), { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: 'Developer diagnostics' })).toHaveFocus();
    enableDiagnostics();
    change('Steps', '7');
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Developer diagnostics' }), { key: 'Home' });
    expect(screen.getByRole('tab', { name: 'Job journal' })).toHaveFocus();
    expect(screen.getByRole('tabpanel', { name: 'Job journal' })).toBeVisible();
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Job journal' }), { key: 'End' });
    expect(screen.getByLabelText('Steps')).toHaveValue(7);
  });

  it('invalidates pending queue consent through snapshot and capability changes without reviving it on return', () => {
    render(<JobsDiagnosticsPreview />);
    enableDiagnostics();
    click('Review queue resume');
    fireEvent.click(screen.getByLabelText('Confirm review of the entire example queue; do not resume it'));
    tab('Job journal');
    change('Snapshot example state', 'empty');
    change('Snapshot example state', 'available');
    tab('Developer diagnostics');
    expect(screen.queryByLabelText('Pending queue resume review')).toBeNull();
    click('Review queue resume');
    expect(screen.getByLabelText('Confirm review of the entire example queue; do not resume it')).not.toBeChecked();
    fireEvent.click(screen.getByLabelText('Confirm review of the entire example queue; do not resume it'));
    change('Diagnostic capability example', 'disabled');
    expect(screen.queryByLabelText('Pending queue resume review')).toBeNull();
    expect(screen.getByRole('button', { name: 'Review queue resume' })).toBeDisabled();
    change('Diagnostic capability example', 'available');
    expect(screen.getByLabelText('Consent to local diagnostic review only')).not.toBeChecked();
  });

  it('does not execute, persist or advance fixture states even after review and elapsed time', () => {
    vi.useFakeTimers();
    const read = vi.spyOn(Storage.prototype, 'getItem');
    const write = vi.spyOn(Storage.prototype, 'setItem');
    const remove = vi.spyOn(Storage.prototype, 'removeItem');
    render(<JobsDiagnosticsPreview />);
    selectJob('example-running');
    click('Review cancellation');
    fireEvent.click(screen.getByLabelText('Confirm this exact example job action; nothing will be sent'));
    click('Freeze job action review');
    enableDiagnostics();
    click('Review diagnostic request');
    click('Review retained retry');
    vi.advanceTimersByTime(60000);
    tab('Job journal');
    expect(inspector().getByText('running')).toBeVisible();
    expect(within(screen.getByRole('table', { name: 'Example job journal' })).getAllByRole('row')).toHaveLength(9);
    expect(fetch).not.toHaveBeenCalled();
    expect(XMLHttpRequest.prototype.open).not.toHaveBeenCalled();
    expect(read).not.toHaveBeenCalled();
    expect(write).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
  });

  it('separates tabs, gates unknown capability, validates bounds and retains frozen inputs across navigation', () => {
    render(<JobsDiagnosticsPreview />);
    expect(screen.queryByRole('spinbutton', { name: 'Steps' })).toBeNull();
    tab('Developer diagnostics');
    expect(screen.queryByRole('table', { name: 'Example job journal' })).toBeNull();
    expect(screen.getByLabelText('Consent to local diagnostic review only')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Review diagnostic request' })).toBeDisabled();
    enableDiagnostics();
    for (const [steps, delay] of [['0', '1'], ['11', '1'], ['1.5', '1'], ['1', '0.09'], ['1', '5.1'], ['', '1'], ['1', '']]) {
      change('Steps', steps);
      change('Delay per step (s)', delay);
      expect(screen.getByRole('button', { name: 'Review diagnostic request' })).toBeDisabled();
    }
    change('Steps', '10');
    change('Delay per step (s)', '5');
    click('Review diagnostic request');
    const frozen = screen.getByLabelText('Frozen diagnostic request').textContent!;
    expect(JSON.parse(frozen)).toMatchObject({ exampleOnly: true, inputs: { steps: 10, delay_seconds: 5 } });
    expect(screen.getByLabelText('Steps')).toBeDisabled();
    tab('Job journal');
    selectJob('example-running');
    tab('Developer diagnostics');
    expect(screen.getByLabelText('Frozen diagnostic request').textContent).toBe(frozen);
    change('Diagnostic capability example', 'unknown');
    expect(screen.getByLabelText('Consent to local diagnostic review only')).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Review retained retry' })).toBeDisabled();
    change('Diagnostic capability example', 'available');
    expect(screen.getByLabelText('Consent to local diagnostic review only')).not.toBeChecked();
    expect(screen.getByLabelText('Frozen diagnostic request').textContent).toBe(frozen);
    expect(screen.getByText(/No custom-input logs, completion result or robotics metrics are generated/)).toBeVisible();
  });

  it('reviews retries with the same retained ID and requires explicit discard without changing frozen reviews', () => {
    render(<JobsDiagnosticsPreview />);
    enableDiagnostics();
    change('Steps', '1');
    change('Delay per step (s)', '0.1');
    click('Review diagnostic request');
    const request = screen.getByLabelText('Frozen diagnostic request').textContent;
    click('Review retained retry');
    expect(screen.getByLabelText('Frozen retry review').textContent).toBe(request);
    expect(screen.getByRole('button', { name: 'Discard retained example state' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Review diagnostic request' })).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Confirm local discard; this does not cancel or resolve a server request'));
    click('Discard retained example state');
    expect(screen.getByLabelText('Retained state summary')).toHaveTextContent('none');
    expect(screen.getByLabelText('Frozen diagnostic request').textContent).toBe(request);
    expect(screen.getByLabelText('Frozen retry review').textContent).toBe(request);
    expect(screen.getByRole('button', { name: 'Review diagnostic request' })).toBeDisabled();
    click('Close frozen diagnostic reviews');
    click('Review diagnostic request');
    expect(JSON.parse(screen.getByLabelText('Frozen diagnostic request').textContent!).idempotency_key).not.toBe(JSON.parse(request!).idempotency_key);
  });

  it.each(['invalid', 'unavailable'])('blocks fresh and retry reviews for %s retained state, rather than replacing it', state => {
    render(<JobsDiagnosticsPreview />);
    enableDiagnostics();
    change('Retained request example state', state);
    expect(screen.getByLabelText('Retained state summary')).toHaveTextContent(state);
    expect(screen.getByRole('button', { name: 'Review diagnostic request' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Review retained retry' })).toBeDisabled();
    expect(screen.queryByLabelText('Frozen diagnostic request')).toBeNull();
    expect(screen.getByLabelText('Retained request example state')).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Confirm local discard; this does not cancel or resolve a server request'));
    click('Discard retained example state');
    expect(screen.getByLabelText('Retained state summary')).toHaveTextContent('none');
    expect(screen.getByLabelText('Confirm local discard; this does not cancel or resolve a server request')).not.toBeChecked();
  });

  it('loads a labelled unresolved request without adopting the selected job and freezes same-ID retry', () => {
    render(<JobsDiagnosticsPreview />);
    selectJob('example-blocked');
    enableDiagnostics();
    change('Retained request example state', 'unresolved');
    expect(screen.getByLabelText('Steps')).toHaveValue(3);
    click('Review retained retry');
    expect(JSON.parse(screen.getByLabelText('Frozen retry review').textContent!)).toMatchObject({ idempotency_key: 'example-retained-diagnostic-001', inputs: { steps: 3, delay_seconds: 1 } });
    expect(screen.getByLabelText('Frozen retry review')).not.toHaveTextContent('example-blocked');
  });

  it('requires explicit full-queue review and confirmation, preserving the frozen cursor without resuming work', () => {
    render(<JobsDiagnosticsPreview />);
    enableDiagnostics();
    click('Review queue resume');
    expect(screen.getByText(/not only diagnostic work/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Freeze queue resume review' })).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Confirm review of the entire example queue; do not resume it'));
    click('Freeze queue resume review');
    const queue = screen.getByLabelText('Frozen queue resume review').textContent;
    expect(JSON.parse(queue!)).toMatchObject({ exampleOnly: true, action: 'resume-queue', cursor: 'example-cursor-008', targets: [{ id: 'example-queued', kind: 'diagnostic', status: 'queued' }] });
    tab('Job journal');
    selectJob('example-queued');
    expect(inspector().getByText('queued')).toBeVisible();
    change('Snapshot example state', 'unavailable');
    tab('Developer diagnostics');
    expect(screen.getByLabelText('Frozen queue resume review').textContent).toBe(queue);
    expect(screen.getByRole('button', { name: 'Review queue resume' })).toBeDisabled();
  });
});

describe('explicit job navigation', () => {
  it('reopens the same ID on a new sequence and clears only pending target consent, retaining frozen reviews', () => {
    const { rerender } = render(<JobsDiagnosticsPreview requestedJob={{ id: 'example-blocked', sequence: 1 }} />);
    change('Authorization example', 'available');
    click('Review authorization renewal');
    fireEvent.click(screen.getByLabelText('Confirm this exact example job action; nothing will be sent'));
    // Ordinary shell renders with the same request must not reset local review state.
    rerender(<JobsDiagnosticsPreview requestedJob={{ id: 'example-blocked', sequence: 1 }} />);
    expect(screen.getByLabelText('Confirm this exact example job action; nothing will be sent')).toBeChecked();
    enableDiagnostics();
    change('Steps', '7');
    click('Review diagnostic request');
    click('Review retained retry');
    click('Review queue resume');
    fireEvent.click(screen.getByLabelText('Confirm review of the entire example queue; do not resume it'));
    click('Freeze queue resume review');
    const diagnostic = screen.getByLabelText('Frozen diagnostic request').textContent;
    const retry = screen.getByLabelText('Frozen retry review').textContent;
    const queue = screen.getByLabelText('Frozen queue resume review').textContent;
    rerender(<JobsDiagnosticsPreview requestedJob={{ id: 'example-blocked', sequence: 2 }} />);
    expect(inspector().getByText('example-blocked')).toBeVisible();
    expect(screen.queryByLabelText('Confirm this exact example job action; nothing will be sent')).toBeNull();
    expect(screen.getByLabelText('Authorization example')).toHaveValue('unknown');
    click('Review cancellation');
    fireEvent.click(screen.getByLabelText('Confirm this exact example job action; nothing will be sent'));
    click('Freeze job action review');
    const jobAction = screen.getByLabelText('Frozen job action review').textContent;
    rerender(<JobsDiagnosticsPreview requestedJob={{ id: 'example-cleanup-pending', sequence: 3 }} />);
    expect(inspector().getByText('example-cleanup-pending')).toBeVisible();
    expect(screen.getByLabelText('Frozen job action review').textContent).toBe(jobAction);
    expect(screen.getByText(/Retained review targets example-blocked, not the selected example-cleanup-pending/)).toBeVisible();
    tab('Developer diagnostics');
    expect(screen.getByLabelText('Frozen diagnostic request').textContent).toBe(diagnostic);
    expect(screen.getByLabelText('Frozen retry review').textContent).toBe(retry);
    expect(screen.getByLabelText('Frozen queue resume review').textContent).toBe(queue);
    // A manual selection may move away, but a new same-ID request reveals it again.
    tab('Job journal');
    selectJob('example-running');
    rerender(<JobsDiagnosticsPreview requestedJob={{ id: 'example-cleanup-pending', sequence: 4 }} />);
    expect(inspector().getByText('example-cleanup-pending')).toBeVisible();
  });

  it.each(['missing-job', '', ' example-blocked '])('never substitutes a fixture for unknown exact ID %j', id => {
    const { rerender } = render(<JobsDiagnosticsPreview />);
    expect(screen.queryByRole('region', { name: 'Exact example job inspector' })).toBeNull();
    selectJob('example-running');
    rerender(<JobsDiagnosticsPreview requestedJob={{ id, sequence: 1 }} />);
    expect(screen.queryByRole('region', { name: 'Exact example job inspector' })).toBeNull();
    expect(screen.getByLabelText('Requested job navigation').textContent).toContain(`Requested job ${id}: not found in the static example snapshot`);
    expect(screen.queryByText('Select a journal entry to inspect its exact example inputs and outcome.')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Review cancellation' })).toBeNull();
    change('Snapshot example state', 'unavailable');
    change('Snapshot example state', 'available');
    expect(screen.queryByRole('region', { name: 'Exact example job inspector' })).toBeNull();
    expect(screen.getByLabelText('Requested job navigation').textContent).toContain(`Requested job ${id}:`);
  });

  it.each(['unavailable', 'empty'])('keeps %s snapshot gating while identifying the exact requested ID', state => {
    const { rerender } = render(<JobsDiagnosticsPreview />);
    selectJob('example-queued');
    change('Snapshot example state', state);
    tab('Developer diagnostics');
    rerender(<JobsDiagnosticsPreview requestedJob={{ id: 'example-cleanup-pending', sequence: 1 }} />);
    expect(screen.getByLabelText('Snapshot example state')).toHaveValue(state);
    expect(screen.queryByRole('region', { name: 'Exact example job inspector' })).toBeNull();
    expect(screen.queryByRole('table', { name: 'Example job journal' })).toBeNull();
    expect(screen.getByLabelText('Requested job navigation')).toHaveTextContent(`example-cleanup-pending: details unavailable in the ${state} example snapshot`);
    expect(screen.queryByRole('button', { name: 'Review cancellation' })).toBeNull();
    change('Snapshot example state', 'available');
    expect(inspector().getByText('example-cleanup-pending')).toBeVisible();
  });

  it('reveals the exact requested job across filters and tabs without remounting diagnostics', () => {
    const { rerender } = render(<JobsDiagnosticsPreview />);
    change('Filter jobs', 'terminal');
    enableDiagnostics();
    change('Steps', '7');
    rerender(<JobsDiagnosticsPreview requestedJob={{ id: 'example-blocked', sequence: 1 }} />);
    expect(screen.getByRole('tab', { name: 'Job journal' })).toHaveAttribute('aria-selected', 'true');
    expect(inspector().getByText('example-blocked')).toBeVisible();
    expect(screen.getByLabelText('Filter jobs')).toHaveValue('all');
    tab('Developer diagnostics');
    expect(screen.getByLabelText('Steps')).toHaveValue(7);
    expect(screen.getByLabelText('Consent to local diagnostic review only')).toBeChecked();
  });
});

describe('offline jobs journal', () => {
  it('exports immutable component-safe summaries projected from every actual journal fixture', () => {
    expect(Array.isArray(exampleJobSummaries)).toBe(true);
    expect(Object.isFrozen(exampleJobSummaries)).toBe(true);
    render(<JobsDiagnosticsPreview />);
    const journalIds = () => within(screen.getByRole('table', { name: 'Example job journal' })).getAllByRole('button').map(button => button.textContent);
    expect(exampleJobSummaries.map(job => job.id)).toEqual(journalIds());
    for (const job of exampleJobSummaries) {
      expect(Object.isFrozen(job)).toBe(true);
      expect(Object.keys(job).sort()).toEqual(['id', 'kind', 'status', 'statusLabel', 'stage', 'isActive', 'needsAttention'].sort());
      selectJob(job.id);
      expect(inspector().getByText(job.statusLabel)).toBeVisible();
      expect(inspector().getByText(job.stage)).toBeVisible();
      expect(job.needsAttention).toBe(['blocked_authorization', 'cancel_requested', 'indeterminate', 'failed'].includes(job.status));
    }
    change('Filter jobs', 'active');
    expect(exampleJobSummaries.filter(job => job.isActive).map(job => job.id)).toEqual(journalIds());
  });

  it('freezes confirmed exact cancellation targets and clears pending consent on A→B→A selection', () => {
    render(<JobsDiagnosticsPreview />);
    selectJob('example-queued');
    click('Review cancellation');
    expect(screen.getByRole('button', { name: 'Freeze job action review' })).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Confirm this exact example job action; nothing will be sent'));
    selectJob('example-running');
    expect(screen.queryByLabelText('Confirm this exact example job action; nothing will be sent')).toBeNull();
    selectJob('example-queued');
    click('Review cancellation');
    expect(screen.getByLabelText('Confirm this exact example job action; nothing will be sent')).not.toBeChecked();
    fireEvent.click(screen.getByLabelText('Confirm this exact example job action; nothing will be sent'));
    click('Freeze job action review');
    const frozen = screen.getByLabelText('Frozen job action review').textContent;
    expect(frozen).toContain('example-queued');
    expect(frozen).toContain('cancel');
    selectJob('example-blocked');
    expect(screen.getByLabelText('Frozen job action review').textContent).toBe(frozen);
    expect(screen.getByText(/Retained review targets example-queued, not the selected example-blocked/)).toBeVisible();
    expect(inspector().getByText('blocked (blocked_authorization)')).toBeVisible();
  });

  it('offers renewal only for eligible blocked generation and never treats unknown authorization as permission', () => {
    render(<JobsDiagnosticsPreview />);
    for (const id of ['example-cleanup-pending', 'example-indeterminate', 'example-succeeded', 'example-failed', 'example-cancelled']) {
      selectJob(id);
      expect(screen.queryByRole('button', { name: 'Review cancellation' })).toBeNull();
      expect(screen.queryByRole('button', { name: 'Review authorization renewal' })).toBeNull();
    }
    selectJob('example-blocked');
    expect(screen.getByRole('button', { name: 'Review authorization renewal' })).toBeDisabled();
    change('Authorization example', 'available');
    click('Review authorization renewal');
    fireEvent.click(screen.getByLabelText('Confirm this exact example job action; nothing will be sent'));
    change('Authorization example', 'unknown');
    expect(screen.queryByLabelText('Confirm this exact example job action; nothing will be sent')).toBeNull();
    change('Authorization example', 'available');
    click('Review authorization renewal');
    expect(screen.getByRole('button', { name: 'Freeze job action review' })).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Confirm this exact example job action; nothing will be sent'));
    click('Freeze job action review');
    const review = JSON.parse(screen.getByLabelText('Frozen job action review').textContent!);
    expect(review).toMatchObject({ exampleOnly: true, action: 'authorization-renewal', target: { id: 'example-blocked', status: 'blocked_authorization' } });
    expect(inspector().getByText('blocked (blocked_authorization)')).toBeVisible();
    expect(screen.queryByText(/renewal succeeded/i)).toBeNull();
  });

  it('filters labelled fixtures and inspects exact immutable job details, not research metrics', () => {
    render(<JobsDiagnosticsPreview />);
    const table = () => within(screen.getByRole('table', { name: 'Example job journal' }));
    expect(table().getAllByRole('row')).toHaveLength(9);
    change('Filter jobs', 'active');
    expect(table().getAllByRole('row')).toHaveLength(5);
    expect(table().queryByText('example-indeterminate')).toBeNull();
    selectJob('example-blocked');
    expect(inspector().getByText('generate')).toBeVisible();
    expect(inspector().getByText('authorization_required')).toBeVisible();
    expect(inspector().getByText('example-owner')).toBeVisible();
    expect(inspector().getByText('2026-01-12T09:00:00Z')).toBeVisible();
    expect(inspector().getByText('2026-01-12T09:01:00Z')).toBeVisible();
    expect(inspector().getByLabelText('Frozen job inputs')).toHaveTextContent('example-source-v1');
    expect(inspector().getByText('No completion result recorded.')).toBeVisible();
    change('Filter jobs', 'terminal');
    expect(table().getAllByRole('row')).toHaveLength(5);
    expect(inspector().getByText('example-blocked')).toBeVisible();
    expect(screen.getByText('Selected job is outside this filter; its inspector remains bound to its exact ID.')).toBeVisible();
    selectJob('example-indeterminate');
    expect(inspector().getByText(/will not be automatically replayed/)).toBeVisible();
    selectJob('example-failed');
    expect(inspector().getByRole('alert')).toHaveTextContent('Example diagnostic failure');
    selectJob('example-succeeded');
    expect(inspector().getByLabelText('Example job result')).toHaveTextContent('fixtureOnly');
  });

  it('withholds stale details when snapshot example state is unavailable without claiming refresh', () => {
    render(<JobsDiagnosticsPreview />);
    selectJob('example-queued');
    expect(screen.getByLabelText('Snapshot cursor')).toHaveTextContent('example-cursor-008');
    change('Snapshot example state', 'unavailable');
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByRole('region', { name: 'Exact example job inspector' })).toBeNull();
    expect(screen.getByLabelText('Snapshot cursor')).toHaveTextContent('Unavailable');
    change('Snapshot example state', 'empty');
    expect(screen.getByText('No example jobs in this snapshot.')).toBeVisible();
    change('Snapshot example state', 'available');
    expect(inspector().getByText('example-queued')).toBeVisible();
  });
});
