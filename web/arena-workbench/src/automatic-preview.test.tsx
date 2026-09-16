import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useAutomaticPreview } from './automatic-preview';

afterEach(() => vi.useRealTimers());

it.each(['identity', 'request', 'ready', 'identity-ABA', 'request-ABA', 'ready-ABA'] as const)(
  'retires automatic dispatch across %s during preflight', async mode => {
    vi.useFakeTimers();
    let allowed!: () => boolean;
    let release!: () => void;
    const submit = vi.fn(async (_payload: Record<string, unknown>, canDispatch: () => boolean) => {
      allowed = canDispatch;
      await new Promise<void>(resolve => { release = resolve; });
    });
    const original = { identity: 'initial', request: { yaml_text: 'initial' }, ready: true };
    const hook = renderHook(props => useAutomaticPreview({ ...props, busy: false, blocked: false, submit }), { initialProps: original });
    act(() => hook.result.current.setEnabled(true));
    const pending = { ...original, identity: 'pending', request: { yaml_text: 'pending' } };
    hook.rerender(pending);
    await act(() => vi.advanceTimersByTimeAsync(1500));
    expect(submit).toHaveBeenCalledOnce();
    expect(allowed()).toBe(true);
    hook.rerender({ ...pending, ...(mode.startsWith('identity') ? { identity: 'other' } : mode.startsWith('request') ? { request: { yaml_text: 'other' } } : { ready: false }) });
    if (mode.endsWith('ABA')) hook.rerender(pending);
    expect(allowed()).toBe(false);
    await act(async () => release());
    act(() => hook.result.current.setEnabled(false));
  },
);

it.each(['off', 'off-on'] as const)('retires the automatic pre-dispatch guard across %s while preflight is unresolved', async mode => {
  vi.useFakeTimers();
  let release!: () => void;
  const dispatch = vi.fn();
  // Model an asynchronous preflight consumer. Missing guards intentionally allow
  // dispatch so this test cannot pass merely because a callback was never supplied.
  const submit = vi.fn(async (_request: Record<string, unknown>, canDispatch?: () => boolean) => {
    await new Promise<void>(resolve => { release = resolve; });
    if (!canDispatch || canDispatch()) dispatch();
  });
  const hook = renderHook(({ identity }) => useAutomaticPreview({
    identity, ready: true, busy: false, blocked: false, request: { yaml_text: identity }, submit,
  }), { initialProps: { identity: 'initial' } });
  act(() => hook.result.current.setEnabled(true));
  hook.rerender({ identity: 'edited' });
  await act(() => vi.advanceTimersByTimeAsync(1500));
  expect(submit).toHaveBeenCalledOnce();
  expect(dispatch).not.toHaveBeenCalled();
  act(() => hook.result.current.setEnabled(false));
  if (mode === 'off-on') act(() => hook.result.current.setEnabled(true));
  await act(async () => { release(); });
  expect(dispatch).not.toHaveBeenCalled();
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  expect(submit).toHaveBeenCalledOnce();
});

it('revokes consent and pending automatic work on inactivity without renewing it on return', async () => {
  vi.useFakeTimers();
  const submit = vi.fn(async () => {});
  const hook = renderHook(({ identity, active }) => useAutomaticPreview({
    identity, active, ready: true, busy: false, blocked: false, request: {}, submit,
  }), { initialProps: { identity: 'initial', active: true } });
  act(() => hook.result.current.setEnabled(true));
  hook.rerender({ identity: 'edited', active: true });
  await act(() => vi.advanceTimersByTimeAsync(1000));
  hook.rerender({ identity: 'edited', active: false });
  expect(hook.result.current.enabled).toBe(false);
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  expect(submit).not.toHaveBeenCalled();
  act(() => hook.result.current.setEnabled(true));
  expect(hook.result.current.enabled).toBe(false);
  hook.rerender({ identity: 'edited', active: true });
  await act(() => vi.advanceTimersByTimeAsync(30_000));
  expect(hook.result.current.enabled).toBe(false);
  expect(submit).not.toHaveBeenCalled();
});

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
  expect(submit).toHaveBeenCalledExactlyOnceWith({ yaml_text: 'edit-2', options: { view: 'edit-2' } }, expect.any(Function));
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
