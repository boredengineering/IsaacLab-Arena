import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useAutomaticPreview } from './automatic-preview';

afterEach(() => vi.useRealTimers());

it('halts on ambiguous submission and never replays after remount or while blocked', async () => {
  vi.useFakeTimers();
  const submit = vi.fn(async () => { throw new Error('connection lost'); });
  const hook = renderHook(({ identity, blocked }) => useAutomaticPreview({
    identity, ready: true, busy: false, blocked, request: { yaml_text: identity }, submit,
  }), { initialProps: { identity: 'initial', blocked: false } });
  act(() => hook.result.current.setEnabled(true));
  hook.rerender({ identity: 'edit-1', blocked: false });
  await act(() => vi.advanceTimersByTimeAsync(1500));
  expect(hook.result.current.halted).toBe(true);
  expect(hook.result.current.count).toBe(1);
  hook.rerender({ identity: 'edit-2', blocked: false });
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  expect(submit).toHaveBeenCalledTimes(1);
  act(() => hook.result.current.setEnabled(false));
  act(() => hook.result.current.setEnabled(true));
  hook.rerender({ identity: 'edit-3', blocked: true });
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  expect(submit).toHaveBeenCalledTimes(1);
  hook.unmount();
  const fresh = renderHook(() => useAutomaticPreview({ identity: 'edit-3', ready: true, busy: false, blocked: false, request: {}, submit }));
  expect(fresh.result.current.enabled).toBe(false);
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  expect(submit).toHaveBeenCalledTimes(1);
});

it('allows one unresolved submission and freezes the candidate before edits', async () => {
  vi.useFakeTimers();
  let release: () => void = () => {};
  const submit = vi.fn((_request: Record<string, unknown>) => new Promise<void>((resolve) => { release = resolve; }));
  const hook = renderHook(({ identity, ready }) => useAutomaticPreview({
    identity, ready, busy: false, blocked: false, request: { yaml_text: identity, options: { view: identity } }, submit,
  }), { initialProps: { identity: 'initial', ready: true } });
  act(() => hook.result.current.setEnabled(true));
  hook.rerender({ identity: 'edit-1', ready: true });
  await act(() => vi.advanceTimersByTimeAsync(1000));
  hook.rerender({ identity: 'invalid', ready: false });
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(submit).not.toHaveBeenCalled();
  hook.rerender({ identity: 'edit-2', ready: true });
  await act(() => vi.advanceTimersByTimeAsync(1500));
  hook.rerender({ identity: 'edit-3', ready: true });
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  expect(submit).toHaveBeenCalledExactlyOnceWith({ yaml_text: 'edit-2', options: { view: 'edit-2' } });
  await act(async () => { release(); });
  act(() => hook.result.current.setEnabled(false));
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  expect(submit).toHaveBeenCalledTimes(1);
});

it('is off by default, debounces validated edits, bounds jobs and never replays an identity', async () => {
  vi.useFakeTimers();
  const submit = vi.fn(async (_payload: Record<string, unknown>) => {});
  const { result, rerender } = renderHook(({ identity, ready, busy }) => useAutomaticPreview({
    identity, ready, busy, blocked: false, request: { yaml_text: identity }, submit,
  }), { initialProps: { identity: 'initial', ready: true, busy: false } });
  await act(() => vi.advanceTimersByTimeAsync(20_000));
  expect(submit).not.toHaveBeenCalled();
  act(() => result.current.setEnabled(true));
  await act(() => vi.advanceTimersByTimeAsync(20_000));
  expect(submit).not.toHaveBeenCalled(); // Enabling is not itself an edit.
  rerender({ identity: 'edit-1', ready: false, busy: false });
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(submit).not.toHaveBeenCalled();
  rerender({ identity: 'edit-1', ready: true, busy: false });
  await act(() => vi.advanceTimersByTimeAsync(1499));
  expect(submit).not.toHaveBeenCalled();
  await act(() => vi.advanceTimersByTimeAsync(1));
  expect(submit).toHaveBeenCalledTimes(1);
  rerender({ identity: 'edit-2', ready: true, busy: true });
  await act(() => vi.advanceTimersByTimeAsync(20_000));
  expect(submit).toHaveBeenCalledTimes(1);
  rerender({ identity: 'edit-2', ready: true, busy: false });
  await act(() => vi.advanceTimersByTimeAsync(1500));
  expect(submit).toHaveBeenCalledTimes(2);
  rerender({ identity: 'edit-1', ready: true, busy: false });
  await act(() => vi.advanceTimersByTimeAsync(1500));
  expect(submit).toHaveBeenCalledTimes(2);
  rerender({ identity: 'edit-3', ready: true, busy: false });
  await act(() => vi.advanceTimersByTimeAsync(8499));
  expect(submit).toHaveBeenCalledTimes(2);
  await act(() => vi.advanceTimersByTimeAsync(1));
  expect(submit).toHaveBeenCalledTimes(3);
  rerender({ identity: 'edit-4', ready: true, busy: false });
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  expect(submit).toHaveBeenCalledTimes(3);
  expect(result.current.count).toBe(3);
  act(() => result.current.setEnabled(false));
  act(() => result.current.setEnabled(true));
  expect(result.current.count).toBe(0);
});
