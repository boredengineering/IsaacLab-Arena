import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkbenchChrome } from './workbench-chrome';
import { readFileSync } from 'node:fs';

// Vitest stubs CSS imports even with ?raw; inspect the actual authored stylesheet.
const chromeCss = readFileSync('src/workbench-v7.css', 'utf8');

const slots = {
  navigation: <nav aria-label="Workspace navigation"><a className="nav-item" href="#editor">Environment editor</a></nav>,
  sessionControls: <button type="button">End session</button>,
  themeControl: <button type="button" role="switch" aria-label="Dark mode" aria-checked={false}>Light</button>,
};

afterEach(() => vi.unstubAllGlobals());

it('exports an opt-in two-row grid, responsive compact rail and locally licensed fonts without global element rules', () => {
  const style = document.createElement('style');
  style.textContent = chromeCss;
  document.head.append(style);
  try {
    const rules = Array.from(style.sheet!.cssRules);

    const regular = rules.filter(rule => rule.type === CSSRule.STYLE_RULE) as CSSStyleRule[];
    const declaration = (selector: string, property: string) => regular.find(rule => rule.selectorText === selector)?.style.getPropertyValue(property);
    expect(declaration('.workbench-v7 .workbench-chrome', 'display')).toBe('contents');
    expect(declaration('.workbench-v7.app-shell', 'grid-template-columns')).toBe('var(--workbench-sidebar-width) minmax(0, 1fr)');
    expect(declaration('.workbench-v7 .main-shell', 'grid-row')).toBe('2');
    expect(declaration('.workbench-v7 .main-shell', 'grid-column')).toBe('2');
    expect(declaration('.workbench-v7 .workbench-globalbar', 'grid-column')).toBe('1 / -1');
    expect(declaration('.workbench-v7 .workbench-sidebar', 'grid-row')).toBe('2');
    expect(declaration('.workbench-v7 .workbench-sidebar', 'grid-column')).toBe('1');
    const media = rules.filter(rule => rule.type === CSSRule.MEDIA_RULE) as CSSMediaRule[];
    expect(media.map(rule => rule.conditionText)).toEqual(expect.arrayContaining(['(max-width: 1150px)', '(max-width: 760px)']));
    const scoped = [...regular, ...media.flatMap(rule => Array.from(rule.cssRules) as CSSStyleRule[])];
    for (const rule of scoped) expect(rule.selectorText).toContain('.workbench-v7');
    expect(chromeCss).not.toMatch(/(?:^|[}\n])\s*(?:body|:root|\*)\s*\{/);
    expect(chromeCss).not.toMatch(/https?:|@import/);
    expect(chromeCss).toContain('[data-sidebar-collapsed="true"]');
    expect(chromeCss).toContain('--workbench-sidebar-width: 68px');
    expect(chromeCss).toContain('min-width: 0');
    expect(chromeCss).toContain('flex-wrap: wrap');
    const fonts = rules.filter(rule => rule.type === CSSRule.FONT_FACE_RULE) as CSSFontFaceRule[];
    expect(fonts).toHaveLength(3);
    for (const font of fonts) expect(font.style.getPropertyValue('src')).toMatch(/\.\/preview\/brand\/.*\.woff2/);
  } finally { style.remove(); }
});

it('uses the accepted display typography only inside the opt-in layout', () => {
  expect(chromeCss).toMatch(/\.workbench-v7 :is\(h1, h2, h3\)\s*\{[^}]*font-family: var\(--font-display\)/);
  const source = readFileSync('src/workbench-chrome.tsx', 'utf8');
  expect(source).toContain("import './workbench-v7.css'");
  const imports = Array.from(source.matchAll(/from ['"]([^'"]+)['"]/g), match => match[1]);
  expect(imports.filter(path => path !== 'react')).toEqual([
    './preview/brand/wordmark.json', './preview/brand/THIRD_PARTY_NOTICES.txt?raw',
  ]);
});

it('publishes readiness after mount only when the callback identity changes', () => {
  const ready = vi.fn(() => expect(screen.getByRole('banner')).toBeInTheDocument());
  const view = render(<WorkbenchChrome {...slots} onReady={ready} />);
  expect(ready).toHaveBeenCalledTimes(1);
  view.rerender(<WorkbenchChrome {...slots} onReady={ready} sessionControls={<button type="button">Reconnect session</button>} />);
  expect(ready).toHaveBeenCalledTimes(1);
  const replacement = vi.fn();
  view.rerender(<WorkbenchChrome {...slots} onReady={replacement} />);
  expect(replacement).toHaveBeenCalledTimes(1);
});

it('collapses to a compact rail without remounting or disabling supplied controls', () => {
  vi.stubGlobal('matchMedia', undefined);
  const endSession = vi.fn();
  const toggleTheme = vi.fn();
  const ready = vi.fn();
  const view = render(<WorkbenchChrome {...slots} onReady={ready}
    themeControl={<button type="button" onClick={toggleTheme}>Change appearance</button>}
    sessionControls={<label>Session note<input defaultValue="retained" /><button type="button" onClick={endSession}>End session</button></label>} />);
  const link = screen.getByRole('link', { name: 'Environment editor' });
  const session = screen.getByRole('button', { name: 'End session' });
  const theme = screen.getByRole('button', { name: 'Change appearance' });
  const note = screen.getByRole('textbox', { name: 'Session note End session' });
  fireEvent.change(note, { target: { value: 'Unsubmitted note' } });
  const toggle = within(screen.getByRole('complementary')).getByRole('button', { name: 'Collapse sidebar' });
  expect(toggle).toHaveAttribute('type', 'button');
  expect(toggle).toHaveAttribute('aria-expanded', 'true');
  expect(document.getElementById(toggle.getAttribute('aria-controls')!)).toContainElement(link);
  fireEvent.click(toggle);
  expect(view.container.firstChild).toHaveAttribute('data-sidebar-collapsed', 'true');
  expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBe(toggle);
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(theme);
  fireEvent.click(session);
  expect(toggleTheme).toHaveBeenCalledTimes(1);
  expect(endSession).toHaveBeenCalledTimes(1);
  fireEvent.click(toggle);
  expect(view.container.firstChild).toHaveAttribute('data-sidebar-collapsed', 'false');
  expect(screen.getByRole('link', { name: 'Environment editor' })).toBe(link);
  expect(screen.getByRole('button', { name: 'End session' })).toBe(session);
  expect(screen.getByRole('button', { name: 'Change appearance' })).toBe(theme);
  expect(note).toHaveValue('Unsubmitted note');
  expect(ready).toHaveBeenCalledTimes(1);
});

it('preserves independent wide and narrow choices across 320, 760, 1050 and 1440 widths', () => {
  const media = new EventTarget();
  let width = 320;
  const query = Object.assign(media, { matches: true, media: '(max-width: 760px)' });
  const subscribe = vi.spyOn(query, 'addEventListener');
  const unsubscribe = vi.spyOn(query, 'removeEventListener');
  const matchMedia = vi.fn(() => query);
  vi.stubGlobal('matchMedia', matchMedia);
  function resize(next: number) {
    width = next;
    act(() => {
      query.matches = width <= 760;
      query.dispatchEvent(Object.assign(new Event('change'), { matches: query.matches }));
    });
  }
  const view = render(<WorkbenchChrome {...slots} />);
  const link = screen.getByRole('link', { name: 'Environment editor' });
  const session = screen.getByRole('button', { name: 'End session' });
  const theme = screen.getByRole('switch', { name: 'Dark mode' });
  expect(screen.getByRole('button', { name: 'Expand sidebar' })).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(screen.getByRole('button', { name: 'Expand sidebar' }));
  resize(760);
  expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument();
  resize(1050);
  expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }));
  resize(1440);
  expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument();
  resize(320);
  expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument();
  resize(1440);
  expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Environment editor' })).toBe(link);
  expect(screen.getByRole('button', { name: 'End session' })).toBe(session);
  expect(screen.getByRole('switch', { name: 'Dark mode' })).toBe(theme);
  expect(matchMedia).toHaveBeenCalledWith('(max-width: 760px)');
  expect(subscribe).toHaveBeenCalledTimes(1);
  view.unmount();
  expect(unsubscribe).toHaveBeenCalledWith('change', subscribe.mock.calls[0][1]);
});

it('handles Escape inside the sidebar without stealing workspace or theme keyboard events', () => {
  render(<><WorkbenchChrome {...slots} /><textarea aria-label="Workspace draft" /></>);
  const link = screen.getByRole('link', { name: 'Environment editor' });
  const draft = screen.getByRole('textbox', { name: 'Workspace draft' });
  draft.focus();
  fireEvent.keyDown(draft, { key: 'Escape' });
  expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument();
  expect(draft).toHaveFocus();
  link.focus();
  fireEvent.keyDown(link, { key: 'Enter' });
  expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument();
  fireEvent.keyDown(link, { key: 'Escape' });
  const toggle = screen.getByRole('button', { name: 'Expand sidebar' });
  expect(toggle).toHaveFocus();
  fireEvent.keyDown(toggle, { key: 'Escape' });
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(toggle);
  const theme = screen.getByRole('switch', { name: 'Dark mode' });
  theme.focus();
  fireEvent.keyDown(theme, { key: 'Escape' });
  expect(theme).toHaveFocus();
  expect(toggle).toHaveAttribute('aria-expanded', 'true');
});

it('ships original font notices and wordmark provenance as static text, not preview runtime', () => {
  render(<WorkbenchChrome {...slots} />);
  const summary = screen.getByText('Typography licenses');
  const details = summary.closest('details');
  expect(details).not.toBeNull();
  fireEvent.click(summary);
  expect(details?.textContent).toContain('SIL OPEN FONT LICENSE Version 1.1');
  expect(details?.textContent).toContain('Tomorrow');
  expect(details?.textContent).toContain('IBM Plex');
  expect(details?.textContent).toContain('Kode Mono');
  expect(details?.textContent).toContain('cyberneticphysics.com');
  expect(details?.textContent).toContain('do not grant rights to the company wordmark');
});

it('mounts only company chrome with the supplied production control slots and no runtime or persistence', () => {
  const forbidden = () => { throw new Error('Chrome must not access runtime or storage'); };
  const fetch = vi.fn(forbidden);
  vi.stubGlobal('fetch', fetch);
  vi.stubGlobal('WebSocket', vi.fn(forbidden));
  vi.stubGlobal('EventSource', vi.fn(forbidden));
  vi.stubGlobal('SharedWorker', vi.fn(forbidden));
  const read = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(forbidden);
  const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(forbidden);
  const { container } = render(<WorkbenchChrome {...slots} />);
  const header = screen.getByRole('banner');
  const aside = screen.getByRole('complementary', { name: 'Workbench sidebar' });
  expect(header.parentElement).toHaveClass('workbench-chrome');
  expect(aside.parentElement).toBe(header.parentElement);
  expect(within(header).getByRole('img', { name: 'Cybernetic-Physics' })).toBeInTheDocument();
  expect(within(header).getByRole('button', { name: 'End session' })).toBeInTheDocument();
  expect(within(header).getByRole('switch', { name: 'Dark mode' })).toBeInTheDocument();
  expect(within(aside).getByRole('navigation', { name: 'Workspace navigation' })).toBeInTheDocument();
  expect(container.querySelector('.main-shell')).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
  expect(read).not.toHaveBeenCalled();
  expect(write).not.toHaveBeenCalled();
  expect(screen.queryByText(/Log in|Sign up|fixture/i)).not.toBeInTheDocument();
});
