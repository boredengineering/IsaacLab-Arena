import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { ActivityPreview } from './activity-preview';
import { exampleJobSummaries, JobsDiagnosticsPreview } from './jobs-diagnostics';

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('offline activity preview', () => {
  it('connects explicit activity clicks to exact journal navigation without a new accepted job or persistence', () => {
    const read = vi.spyOn(Storage.prototype, 'getItem');
    const write = vi.spyOn(Storage.prototype, 'setItem');
    const remove = vi.spyOn(Storage.prototype, 'removeItem');
    function ConnectedPreview() {
      const [requestedJob, setRequestedJob] = React.useState<{ id: string; sequence: number }>();
      return <>
        <ActivityPreview onInspectJob={id => setRequestedJob(previous => ({ id, sequence: (previous?.sequence ?? 0) + 1 }))} onOpenEvidence={vi.fn()} />
        <JobsDiagnosticsPreview requestedJob={requestedJob} />
      </>;
    }
    render(<ConnectedPreview />);
    const activity = within(screen.getByRole('region', { name: 'Activity preview' }));
    expect(screen.queryByRole('region', { name: 'Exact example job inspector' })).toBeNull();
    fireEvent.click(activity.getByRole('button', { name: 'Show example jobs' }));
    fireEvent.click(activity.getByRole('button', { name: 'Inspect example-blocked' }));
    expect(within(screen.getByRole('region', { name: 'Exact example job inspector' })).getByText('example-blocked')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Review cancellation' }));
    fireEvent.click(screen.getByLabelText('Confirm this exact example job action; nothing will be sent'));
    fireEvent.click(screen.getByRole('tab', { name: 'Developer diagnostics' }));
    fireEvent.click(activity.getByRole('button', { name: 'Inspect example-blocked' }));
    expect(screen.getByRole('tab', { name: 'Job journal' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByLabelText('Confirm this exact example job action; nothing will be sent')).toBeNull();
    fireEvent.change(screen.getByLabelText('Snapshot example state'), { target: { value: 'unavailable' } });
    fireEvent.click(activity.getByRole('button', { name: 'Inspect example-cleanup-pending' }));
    expect(screen.getByLabelText('Requested job navigation')).toHaveTextContent('example-cleanup-pending: details unavailable');
    expect(screen.queryByRole('region', { name: 'Exact example job inspector' })).toBeNull();
    fireEvent.change(screen.getByLabelText('Snapshot example state'), { target: { value: 'available' } });
    expect(within(screen.getByRole('region', { name: 'Exact example job inspector' })).getByText('example-cleanup-pending')).toBeVisible();
    expect(within(screen.getByRole('table', { name: 'Example job journal' })).getAllByRole('button')).toHaveLength(exampleJobSummaries.length);
    expect(fetch).not.toHaveBeenCalled();
    expect(XMLHttpRequest.prototype.open).not.toHaveBeenCalled();
    expect(read).not.toHaveBeenCalled();
    expect(write).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
  });

  it('opens independent research examples, not artifacts proven by an activity job', () => {
    const onInspectJob = vi.fn();
    const onOpenEvidence = vi.fn();
    const read = vi.spyOn(Storage.prototype, 'getItem');
    const write = vi.spyOn(Storage.prototype, 'setItem');
    render(<ActivityPreview onInspectJob={onInspectJob} onOpenEvidence={onOpenEvidence} />);
    expect(screen.getByText(/Independent research examples.*not proven artifacts of these jobs/)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Open independent research examples' }));
    expect(onOpenEvidence.mock.calls).toEqual([[]]);
    expect(onInspectJob).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
    expect(XMLHttpRequest.prototype.open).not.toHaveBeenCalled();
    expect(read).not.toHaveBeenCalled();
    expect(write).not.toHaveBeenCalled();
  });

  it('expands exact fixture navigation without creating jobs, fetching or storing state', () => {
    vi.useFakeTimers();
    const read = vi.spyOn(Storage.prototype, 'getItem');
    const write = vi.spyOn(Storage.prototype, 'setItem');
    const remove = vi.spyOn(Storage.prototype, 'removeItem');
    const onInspectJob = vi.fn();
    const onOpenEvidence = vi.fn();
    const before = JSON.stringify(exampleJobSummaries);
    render(<ActivityPreview onInspectJob={onInspectJob} onOpenEvidence={onOpenEvidence} />);
    const expand = screen.getByRole('button', { name: 'Show example jobs' });
    expect(expand).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('button', { name: 'Inspect example-blocked' })).toBeNull();
    expect(onInspectJob).not.toHaveBeenCalled();
    fireEvent.click(expand);
    const collapse = screen.getByRole('button', { name: 'Hide example jobs' });
    expect(collapse).toHaveAttribute('aria-expanded', 'true');
    const list = screen.getByRole('list', { name: 'Activity example jobs' });
    expect(collapse.getAttribute('aria-controls')).toBe(list.id);
    expect(within(list).getAllByRole('listitem')).toHaveLength(exampleJobSummaries.length);
    for (const job of exampleJobSummaries) {
      const link = within(list).getByRole('button', { name: `Inspect ${job.id}` });
      expect(within(link.closest('li')!).getByText(job.statusLabel)).toBeVisible();
      fireEvent.click(link);
      expect(onInspectJob).toHaveBeenLastCalledWith(job.id);
    }
    expect(onInspectJob).toHaveBeenCalledTimes(exampleJobSummaries.length);
    expect(onInspectJob).toHaveBeenCalledWith('example-blocked');
    expect(onInspectJob).toHaveBeenCalledWith('example-cleanup-pending');
    fireEvent.click(collapse);
    expect(screen.queryByRole('list', { name: 'Activity example jobs' })).toBeNull();
    vi.advanceTimersByTime(60000);
    expect(JSON.stringify(exampleJobSummaries)).toBe(before);
    expect(onOpenEvidence).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
    expect(XMLHttpRequest.prototype.open).not.toHaveBeenCalled();
    expect(read).not.toHaveBeenCalled();
    expect(write).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
  });

  it('labels static disconnected activity and derives counts from the journal summaries', () => {
    render(<ActivityPreview onInspectJob={vi.fn()} onOpenEvidence={vi.fn()} />);
    const activity = within(screen.getByRole('region', { name: 'Activity preview' }));
    expect(activity.getByText(/Static example fixtures.*Disconnected/)).toBeVisible();
    expect(activity.getByText(/not accepted jobs.*current draft.*historical images/)).toBeVisible();
    expect(activity.getByLabelText('Active example jobs')).toHaveTextContent(String(exampleJobSummaries.filter(job => job.isActive).length));
    expect(activity.getByLabelText('Attention example jobs')).toHaveTextContent(String(exampleJobSummaries.filter(job => job.needsAttention).length));
    expect(activity.getByText(/Counts overlap/)).toBeVisible();
  });
});
