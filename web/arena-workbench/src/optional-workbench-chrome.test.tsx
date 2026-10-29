import { act, fireEvent, render, screen } from '@testing-library/react';
import { StrictMode, useEffect } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import type { WorkbenchChromeProps } from './workbench-chrome';
import { OptionalWorkbenchChrome, type WorkbenchChromeLoader } from './optional-workbench-chrome';

const slots = {
  navigation: <nav>Workspace navigation</nav>,
  sessionControls: <button type="button">Session</button>,
  themeControl: <button type="button">Theme</button>,
};

function deferred() {
  let resolve!: (module: Awaited<ReturnType<WorkbenchChromeLoader>>) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<Awaited<ReturnType<WorkbenchChromeLoader>>>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function Chrome({ navigation, sessionControls, themeControl, onReady }: WorkbenchChromeProps) {
  useEffect(() => { onReady?.(); }, [onReady]);
  return <header aria-label="Loaded chrome">{navigation}{sessionControls}{themeControl}</header>;
}

afterEach(() => vi.restoreAllMocks());

it('keeps sibling fallback usable while pending and reports readiness only after chrome mounts', async () => {
  const pending = deferred();
  const loader = vi.fn(() => pending.promise);
  const ready = vi.fn(() => expect(screen.getByRole('banner', { name: 'Loaded chrome' })).toBeInTheDocument());
  const failure = vi.fn();
  const fallback = vi.fn();
  render(<><button onClick={fallback}>Fallback navigation</button><OptionalWorkbenchChrome {...slots} enabled loader={loader} onReady={ready} onFailure={failure} /></>);
  await act(async () => {});
  expect(loader).toHaveBeenCalledTimes(1);
  expect(ready).not.toHaveBeenCalled();
  expect(screen.queryByRole('banner')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Fallback navigation' }));
  expect(fallback).toHaveBeenCalledTimes(1);
  await act(async () => pending.resolve({ WorkbenchChrome: Chrome }));
  expect(ready).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('navigation')).toHaveTextContent('Workspace navigation');
  expect(screen.getByRole('button', { name: 'Session' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Theme' })).toBeInTheDocument();
  expect(failure).not.toHaveBeenCalled();
});

it('reports a rejected import once without disturbing the parent fallback', async () => {
  const pending = deferred();
  const loader = vi.fn(() => pending.promise);
  const ready = vi.fn();
  const failure = vi.fn();
  const fallback = vi.fn();
  const tree = () => <><button onClick={fallback}>Fallback navigation</button><OptionalWorkbenchChrome {...slots} enabled loader={loader} onReady={ready} onFailure={failure} /></>;
  const view = render(tree());
  await act(async () => pending.reject(new Error('chunk unavailable')));
  expect(failure).toHaveBeenCalledTimes(1);
  expect(ready).not.toHaveBeenCalled();
  expect(screen.queryByRole('banner')).not.toBeInTheDocument();
  view.rerender(tree());
  expect(loader).toHaveBeenCalledTimes(1);
  expect(failure).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Fallback navigation' }));
  expect(fallback).toHaveBeenCalledTimes(1);
});

it.each([false, true])('contains render exceptions (after readiness: %s)', async afterReady => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  const ready = vi.fn();
  const failure = vi.fn();
  const fallback = vi.fn();
  let crash = !afterReady;
  function Breakable(props: WorkbenchChromeProps) {
    if (crash) throw new Error('chrome render failed');
    return <Chrome {...props} />;
  }
  const loader = vi.fn(async () => ({ WorkbenchChrome: Breakable }));
  const tree = () => <><button onClick={fallback}>Fallback navigation</button><OptionalWorkbenchChrome {...slots} enabled loader={loader} onReady={ready} onFailure={failure} /></>;
  const view = render(tree());
  await act(async () => {});
  if (afterReady) {
    expect(ready).toHaveBeenCalledTimes(1);
    crash = true;
    view.rerender(tree());
  }
  expect(ready).toHaveBeenCalledTimes(afterReady ? 1 : 0);
  expect(failure).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('banner')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Fallback navigation' }));
  expect(fallback).toHaveBeenCalledTimes(1);
  view.rerender(tree());
  expect(failure).toHaveBeenCalledTimes(1);
});

it('retires delayed child readiness on disable even after a replacement activation mounts', async () => {
  const signals: Array<() => void> = [];
  function DelayedChrome({ onReady }: WorkbenchChromeProps) {
    useEffect(() => { signals.push(onReady!); }, [onReady]);
    return <header aria-label="Delayed chrome" />;
  }
  const loader = vi.fn(async () => ({ WorkbenchChrome: DelayedChrome }));
  const ready = vi.fn();
  const failure = vi.fn();
  const tree = (enabled: boolean) => <OptionalWorkbenchChrome {...slots} enabled={enabled} loader={loader} onReady={ready} onFailure={failure} />;
  const view = render(tree(true));
  await act(async () => {});
  expect(ready).not.toHaveBeenCalled();
  view.rerender(tree(false));
  act(() => signals[0]());
  expect(ready).not.toHaveBeenCalled();
  view.rerender(tree(true));
  await act(async () => {});
  act(() => signals[0]());
  expect(ready).not.toHaveBeenCalled();
  act(() => signals[1]());
  expect(ready).toHaveBeenCalledTimes(1);
  act(() => signals[1]());
  expect(ready).toHaveBeenCalledTimes(1);
  expect(loader).toHaveBeenCalledTimes(2);
  expect(failure).not.toHaveBeenCalled();
});

it.each(['resolve', 'reject'] as const)('ignores retired import %s after disable and re-enable', async settlement => {
  const old = deferred();
  const current = deferred();
  const loader = vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
  const ready = vi.fn();
  const failure = vi.fn();
  const tree = (enabled: boolean) => <OptionalWorkbenchChrome {...slots} enabled={enabled} loader={loader} onReady={ready} onFailure={failure} />;
  const view = render(tree(true));
  view.rerender(tree(false));
  view.rerender(tree(true));
  await act(async () => {
    if (settlement === 'resolve') old.resolve({ WorkbenchChrome: Chrome });
    else old.reject(new Error('retired import'));
  });
  expect(ready).not.toHaveBeenCalled();
  expect(failure).not.toHaveBeenCalled();
  expect(screen.queryByRole('banner')).not.toBeInTheDocument();
  await act(async () => current.resolve({ WorkbenchChrome: Chrome }));
  expect(ready).toHaveBeenCalledTimes(1);
  expect(failure).not.toHaveBeenCalled();
});

it.each(['resolve', 'reject'] as const)('starts one StrictMode import and uses latest callbacks on %s without reloading', async settlement => {
  const pending = deferred();
  const loader = vi.fn(() => pending.promise);
  const unusedLoader = vi.fn(() => deferred().promise);
  const ready = vi.fn();
  const failure = vi.fn();
  const latestReady = vi.fn();
  const latestFailure = vi.fn();
  const view = render(<StrictMode><OptionalWorkbenchChrome {...slots} enabled loader={loader} onReady={ready} onFailure={failure} /></StrictMode>);
  view.rerender(<StrictMode><OptionalWorkbenchChrome {...slots} enabled loader={unusedLoader} onReady={() => latestReady()} onFailure={() => latestFailure()} /></StrictMode>);
  await act(async () => {});
  expect(loader).toHaveBeenCalledTimes(1);
  expect(unusedLoader).not.toHaveBeenCalled();
  await act(async () => {
    if (settlement === 'resolve') pending.resolve({ WorkbenchChrome: Chrome });
    else pending.reject(new Error('strict import failure'));
  });
  expect(ready).not.toHaveBeenCalled();
  expect(failure).not.toHaveBeenCalled();
  expect(latestReady).toHaveBeenCalledTimes(settlement === 'resolve' ? 1 : 0);
  expect(latestFailure).toHaveBeenCalledTimes(settlement === 'reject' ? 1 : 0);
  view.rerender(<StrictMode><OptionalWorkbenchChrome {...slots} enabled loader={unusedLoader} onReady={() => latestReady()} onFailure={() => latestFailure()} /></StrictMode>);
  expect(latestReady).toHaveBeenCalledTimes(settlement === 'resolve' ? 1 : 0);
  expect(latestFailure).toHaveBeenCalledTimes(settlement === 'reject' ? 1 : 0);
  expect(unusedLoader).not.toHaveBeenCalled();
});

it('contains a synchronous loader exception under StrictMode', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  const loader = vi.fn(() => { throw new Error('loader failed before returning a promise'); });
  const ready = vi.fn();
  const failure = vi.fn();
  const view = render(<StrictMode><OptionalWorkbenchChrome {...slots} enabled loader={loader} onReady={ready} onFailure={failure} /></StrictMode>);
  await act(async () => {});
  expect(view.container).toBeEmptyDOMElement();
  expect(loader).toHaveBeenCalledTimes(1);
  expect(failure).toHaveBeenCalledTimes(1);
  expect(ready).not.toHaveBeenCalled();
});

it('ignores readiness after failure and allows a fresh activation to recover', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  let signal!: () => void;
  let crash = false;
  function Breakable({ onReady }: WorkbenchChromeProps) {
    useEffect(() => { signal = onReady!; }, [onReady]);
    if (crash) throw new Error('chrome failed after reporting ready');
    return <header aria-label="Recoverable chrome" />;
  }
  const loader = vi.fn(async () => ({ WorkbenchChrome: Breakable }));
  const ready = vi.fn();
  const failure = vi.fn();
  const latestFailure = vi.fn();
  const tree = (enabled: boolean, onFailure = failure) => <OptionalWorkbenchChrome {...slots} enabled={enabled} loader={loader} onReady={ready} onFailure={onFailure} />;
  const view = render(tree(true));
  await act(async () => {});
  act(() => signal());
  expect(ready).toHaveBeenCalledTimes(1);
  const retiredSignal = signal;
  crash = true;
  view.rerender(tree(true, latestFailure));
  expect(latestFailure).toHaveBeenCalledTimes(1);
  expect(failure).not.toHaveBeenCalled();
  act(() => retiredSignal());
  expect(ready).toHaveBeenCalledTimes(1);
  view.rerender(tree(false));
  crash = false;
  view.rerender(tree(true));
  await act(async () => {});
  act(() => retiredSignal());
  expect(ready).toHaveBeenCalledTimes(1);
  act(() => signal());
  expect(ready).toHaveBeenCalledTimes(2);
  expect(loader).toHaveBeenCalledTimes(2);
});

it('loads the real chrome by default only on activation', async () => {
  const imported = vi.fn();
  vi.doMock('./workbench-chrome', async () => {
    imported();
    return vi.importActual('./workbench-chrome');
  });
  try {
    const ready = vi.fn(() => expect(screen.getByRole('img', { name: 'Cybernetic-Physics' })).toBeInTheDocument());
    const failure = vi.fn();
    const view = render(<OptionalWorkbenchChrome {...slots} enabled={false} onReady={ready} onFailure={failure} />);
    await act(async () => {});
    expect(imported).not.toHaveBeenCalled();
    expect(ready).not.toHaveBeenCalled();
    view.rerender(<OptionalWorkbenchChrome {...slots} enabled onReady={ready} onFailure={failure} />);
    await screen.findByRole('img', { name: 'Cybernetic-Physics' });
    expect(imported).toHaveBeenCalledTimes(1);
    expect(ready).toHaveBeenCalledTimes(1);
    expect(failure).not.toHaveBeenCalled();
  } finally {
    vi.doUnmock('./workbench-chrome');
  }
});

it('does not start the optional import while disabled', () => {
  const loader = vi.fn(() => deferred().promise);
  const ready = vi.fn();
  const failure = vi.fn();
  const view = render(<OptionalWorkbenchChrome {...slots} enabled={false} loader={loader} onReady={ready} onFailure={failure} />);
  expect(view.container).toBeEmptyDOMElement();
  expect(loader).not.toHaveBeenCalled();
  expect(ready).not.toHaveBeenCalled();
  expect(failure).not.toHaveBeenCalled();
});
