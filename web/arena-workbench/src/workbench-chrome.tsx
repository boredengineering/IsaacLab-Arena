import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import wordmark from './preview/brand/wordmark.json';
import notices from './preview/brand/THIRD_PARTY_NOTICES.txt?raw';
import './workbench-v7.css';

export interface WorkbenchChromeProps {
  navigation: ReactNode;
  sessionControls: ReactNode;
  themeControl: ReactNode;
  onReady?: () => void;
}

/** Presentation only: the parent retains all workspace and session ownership. */
export function WorkbenchChrome({ navigation, sessionControls, themeControl, onReady }: WorkbenchChromeProps) {
  const [media] = useState(() => typeof window === 'undefined' ? undefined : window.matchMedia?.('(max-width: 760px)'));
  const [narrow, setNarrow] = useState(media?.matches ?? false);
  const [preferences, setPreferences] = useState({ wide: false, narrow: true });
  const layout = narrow ? 'narrow' : 'wide';
  const collapsed = preferences[layout];
  const setCollapsed = (value: boolean) => setPreferences(previous => ({ ...previous, [layout]: value }));
  const navigationId = useId();
  const toggleRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!media) return;
    const resize = (event: MediaQueryListEvent) => setNarrow(event.matches);
    media.addEventListener('change', resize);
    return () => media.removeEventListener('change', resize);
  }, [media]);
  useEffect(() => { onReady?.(); }, [onReady]);
  return (
    <div className="workbench-chrome" data-sidebar-collapsed={collapsed}>
      <header className="workbench-globalbar">
        <div className="workbench-brand">
          <svg className="workbench-wordmark" role="img" aria-label="Cybernetic-Physics" viewBox={wordmark.viewBox} fill="currentColor" focusable="false">
            <title>Cybernetic-Physics</title>
            {wordmark.paths.map((path, index) => <path key={index} d={path} />)}
          </svg>
          <small>Research workbench</small>
        </div>
        <div className="workbench-account-actions">
          <div className="workbench-theme-control">{themeControl}</div>
          <div className="workbench-session-controls">{sessionControls}</div>
        </div>
      </header>
      <aside className="workbench-sidebar" aria-label="Workbench sidebar" onKeyDown={event => {
        if (event.key !== 'Escape' || event.defaultPrevented || collapsed) return;
        event.preventDefault();
        event.stopPropagation();
        setCollapsed(true);
        toggleRef.current?.focus();
      }}>
        <div className="workbench-sidebar-heading">
          <span className="workbench-sidebar-label">Workspace</span>
          <button ref={toggleRef} type="button" className="workbench-sidebar-toggle"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed} aria-controls={navigationId}
            onClick={() => setCollapsed(!collapsed)}>
            <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <rect x="3" y="4" width="18" height="16" rx="1" /><path d="M9 4v16" />
              <path d={collapsed ? 'm13 9 3 3-3 3' : 'm16 9-3 3 3 3'} />
            </svg>
          </button>
        </div>
        <div className="workbench-navigation" id={navigationId}>{navigation}</div>
        <details className="workbench-font-notices">
          <summary title="Typography licenses"><span aria-hidden="true" className="workbench-license-marker">Aa</span><span className="workbench-license-label">Typography licenses</span></summary>
          <div className="workbench-license-content">
            <p>Company wordmark: cyberneticphysics.com. Font licenses do not grant rights to the company wordmark. Light mode is a workbench adaptation.</p>
            <pre>{notices}</pre>
          </div>
        </details>
      </aside>
    </div>
  );
}
