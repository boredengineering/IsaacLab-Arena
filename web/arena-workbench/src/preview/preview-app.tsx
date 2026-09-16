import { useEffect, useRef, useState, type ReactNode } from 'react';
import { EnvironmentPanel } from './environment';
import { EnvironmentPicker, LibraryPanel } from './library';
import { WorkflowPanels } from './workflow-panels';
import { CoveragePanel } from './coverage';
import { CompanyWordmark, TypographyLicenses } from './company-brand';
import { PreviewThemeToggle } from './preview-theme-toggle';
import { Neo4jQueryPreview } from './neo4j-query';
import { JobsDiagnosticsPreview } from './jobs-diagnostics';
import { ActivityPreview } from './activity-preview';
import { AssetSceneVisualizer } from './asset-scene-visualizer';
import { visualizerFrames } from './visualizer-frames';
import { InspectCorrectWorkspace } from './inspect-correct-workspace';
import { inspectionVersions } from './inspection-data';
import type { PreviewContext, PreviewSection, PreviewSelection } from './types';

const destinations: { id: PreviewSection; label: string; description: string }[] = [
 { id: 'environment', label: 'Environment', description: 'Start from a prompt. Review the specification and its evidence.' },
 { id: 'library', label: 'Library', description: 'Choose a family, then a version. Keep policies and experiments separate.' },
 { id: 'visualizer', label: 'Assets & scene', description: 'Inspect saved render captures and plan visualization. Live RTX remains a separate, unconnected capability.' },
 { id: 'build', label: 'Build & evaluate', description: 'Review exact inputs, runtime purpose and resource limits.' },
 { id: 'improve', label: 'Improve', description: 'Propose changes from evidence without silently accepting or rerunning them.' },
 { id: 'experiments', label: 'Experiments', description: 'Plan variations, bounded children and comparisons.' },
 { id: 'runs', label: 'Runs & evidence', description: 'Inspect research reports, metrics and media independently of operational job controls.' },
 { id: 'neo4j', label: 'Neo4j query', description: 'Review read-only Cypher and labelled result examples. Publication is a separate workspace.' },
 { id: 'graph', label: 'Research graph', description: 'Inspect publication intent and persisted-graph concepts, not the authored draft.' },
 { id: 'jobs', label: 'Jobs & diagnostics', description: 'Inspect operational job records and integration diagnostics, not research success metrics.' },
 { id: 'settings', label: 'Settings & readiness', description: 'Understand prerequisites and ownership. No credentials are accepted here.' },
 { id: 'coverage', label: 'Coverage & reference', description: 'Inspect the planned capability and option inventory; record gaps before integration.' },
];
function ReviewDialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
 const ref = useRef<HTMLDialogElement>(null);
 useEffect(() => { const node = ref.current; node?.showModal(); return () => node?.close(); }, []);
 return <dialog ref={ref} className="preview-dialog" aria-label={title} onCancel={e => { e.preventDefault(); onClose(); }}><h2>{title}</h2>{children}</dialog>;
}
export function PreviewApp() {
 const [section, setSection] = useState<PreviewSection>('environment');
 const [visited, setVisited] = useState<Set<PreviewSection>>(new Set(['environment']));
 const [selection, setSelection] = useState<PreviewSelection | null>(null);
 const [draft, setDraft] = useState('');
 const [prompt, setPrompt] = useState('');
 const [composerEpoch, setComposerEpoch] = useState(0);
 const [composerDirty, setComposerDirty] = useState(false);
 const [composerExpanded, setComposerExpanded] = useState(true);
 const [activityOpen, setActivityOpen] = useState(false);
 const [requestedJob, setRequestedJob] = useState<{ id: string; sequence: number }>();
 const [theme, setTheme] = useState<'dark' | 'light'>('dark');
 const [narrow, setNarrow] = useState(() => window.matchMedia?.('(max-width: 760px)').matches ?? false);
 const [sidebarPreference, setSidebarPreference] = useState({ wide: false, narrow: true });
 const collapsed = sidebarPreference[narrow ? 'narrow' : 'wide'];
 function setCollapsed(update: boolean | ((value: boolean) => boolean)) {
  const layout = narrow ? 'narrow' : 'wide';
  setSidebarPreference(previous => ({ ...previous, [layout]: typeof update === 'function' ? update(previous[layout]) : update }));
 }
 const [accountView, setAccountView] = useState<'login' | 'signup' | null>(null);
 const sidebarToggle = useRef<HTMLButtonElement>(null);
 const [pending, setPending] = useState<{ kind: 'open'; selection: PreviewSelection } | { kind: 'new' } | null>(null);
 const [saveDraft, setSaveDraft] = useState<string | null>(null);
 const [saveName, setSaveName] = useState('Example working environment');
 const [localVersions, setLocalVersions] = useState<PreviewSelection[]>([]);
 const dirty = draft !== (selection?.yaml ?? '');
 const hasUnsaved = dirty || Boolean(prompt.trim()) || composerDirty;
 const context: PreviewContext = { familyId: selection?.familyId ?? null, versionId: selection?.versionId ?? null, familyName: selection?.familyName ?? 'New environment', versionLabel: selection ? `v${selection.version}` : 'Unsaved draft', robot: selection?.robot ?? 'Unselected', hand: selection?.hand ?? 'Unselected', dirty };
 useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
 useEffect(() => {
  const query = window.matchMedia?.('(max-width: 760px)');
  if (!query) return;
  const resize = (event: MediaQueryListEvent) => { setNarrow(event.matches); if (event.matches) setSidebarPreference(previous => ({ ...previous, narrow: true })); };
  query.addEventListener('change', resize);
  return () => query.removeEventListener('change', resize);
 }, []);
 function navigate(next: PreviewSection) { setActivityOpen(false); setSection(next); setVisited(previous => new Set([...previous, next])); if (narrow) setCollapsed(true); }
 function open(next: PreviewSelection | null) { setSelection(next); setDraft(next?.yaml ?? ''); setPrompt(''); setComposerDirty(false); setComposerExpanded(next?.familyId !== 'example-inspection'); setComposerEpoch(value => value + 1); navigate('environment'); }
 function requestOpen(next: PreviewSelection) { if (hasUnsaved) setPending({ kind: 'open', selection: next }); else open(next); }
 function saveExample() {
  if (saveDraft === null || !saveName.trim()) return;
  const serial = localVersions.length + 1;
  const next: PreviewSelection = { familyId: 'example-local-family', familyName: saveName.trim(), versionId: `example-local-${serial}`, version: serial, source: `example-only/session/version-${serial}.yaml`, yaml: saveDraft, robot: selection?.robot ?? 'Unspecified example', hand: selection?.hand ?? 'Unspecified example' };
  setLocalVersions(previous => [...previous, next]); setSelection(next); setSaveDraft(null); setComposerDirty(false); setComposerEpoch(value => value + 1);
 }
 const current = destinations.find(d => d.id === section)!;
 const independentWorkspace = ['neo4j', 'jobs', 'runs', 'visualizer'].includes(section);
 return <div className={`preview-app${collapsed ? ' sidebar-collapsed' : ''}`}>
  <a className="preview-skip" href="#preview-main">Skip to workspace</a>
  <header className="preview-globalbar" aria-label="Preview top bar">
   <div className="preview-brand"><CompanyWordmark /><small>Research workbench</small></div>
   <span className="preview-version">Preview v7</span>
   <div className="preview-account-actions">
    <PreviewThemeToggle theme={theme} onToggle={() => setTheme(value => value === 'dark' ? 'light' : 'dark')} />
    <button className="quiet" onClick={() => setAccountView('login')}>Login</button>
    <button className="primary" onClick={() => setAccountView('signup')}>Sign up</button>
   </div>
  </header>
  <aside className="preview-sidebar" aria-label="Workspace sidebar" onKeyDown={event => { if (event.key === 'Escape' && !collapsed) { setCollapsed(true); sidebarToggle.current?.focus(); } }}>
   <div className="preview-sidebar-heading"><span className="preview-eyebrow preview-sidebar-label">WORKSPACE</span>
    <button ref={sidebarToggle} className="preview-sidebar-toggle" aria-label={collapsed ? 'Expand left sidebar' : 'Collapse left sidebar'} title={collapsed ? 'Expand left sidebar' : 'Collapse left sidebar'} aria-expanded={!collapsed} aria-controls="preview-navigation" onClick={() => setCollapsed(value => !value)}>
     <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true"><rect x="2" y="3" width="16" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" /><path d="M7 3v14" stroke="currentColor" strokeWidth="1.5" /></svg>
    </button>
   </div>
   <nav id="preview-navigation" aria-label="Preview navigation">{destinations.map((d, i) => <button key={d.id} aria-label={d.label} title={collapsed ? d.label : undefined} aria-current={section === d.id ? 'page' : undefined} onClick={() => navigate(d.id)}><span className="preview-nav-marker" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span><span className="preview-nav-label">{d.label}</span></button>)}</nav>
   <div className="preview-sidebar-note"><strong>Review the workflow first</strong><p>Find missing steps and simplify before connecting real execution.</p></div>
  </aside>
  <div className="preview-main-shell"><div className="preview-banner"><strong>Design preview</strong><span>Example data · no jobs or database operations · no live API</span></div>
   <div className="preview-topbar"><div><span className="preview-eyebrow">LOCAL EXAMPLES / {current.label.toUpperCase()}</span><h1 aria-label={current.label}>{current.label}</h1><p>{current.description}</p></div><span className="preview-status">Execution disabled</span></div>
   <section className="preview-context" hidden={independentWorkspace} aria-label="Selected environment context"><div data-testid="selection-context"><strong>{context.familyName}</strong><span>{context.versionLabel} · {selection?.versionId ?? 'No saved version selected'}</span><small>{dirty ? 'Draft differs from selected version' : selection ? 'Draft matches this example version' : 'No template required'}</small></div><div className="preview-actions"><button onClick={() => hasUnsaved ? setPending({ kind: 'new' }) : open(null)}>Start new draft</button><button disabled={!draft.trim()} onClick={() => { setSaveDraft(draft); setSaveName(selection?.familyName ?? 'Example working environment'); }}>Review version save</button></div></section>
   <div className="preview-utilitybar"><button type="button" aria-expanded={activityOpen} aria-controls="preview-activity-drawer" onClick={() => setActivityOpen(value => !value)}>Activity examples</button><span className="preview-muted">Disconnected · no live jobs</span></div>
   <div id="preview-activity-drawer" className="preview-activity-drawer" hidden={!activityOpen}><ActivityPreview onInspectJob={id => { setRequestedJob(previous => ({ id, sequence: (previous?.sequence ?? 0) + 1 })); navigate('jobs'); }} onOpenEvidence={() => navigate('runs')} /></div>
   <main id="preview-main">
    <section hidden={!['environment', 'visualizer'].includes(section)} aria-label={section === 'visualizer' ? 'Assets & scene workspace' : 'Environment workspace'}>
     <div hidden={section === 'visualizer'}>
      <EnvironmentPicker selection={selection} onOpen={requestOpen} onBrowse={() => navigate('library')} />
      <button type="button" className="preview-composer-toggle" aria-expanded={composerExpanded} aria-controls="preview-generation-controls" onClick={() => setComposerExpanded(value => !value)}>{composerExpanded ? 'Hide generation controls' : 'Show generation controls'}</button>
      <div id="preview-generation-controls" hidden={!composerExpanded}><EnvironmentPanel key={composerEpoch} selection={selection} draft={draft} prompt={prompt} onDraft={setDraft} onPrompt={setPrompt} onComposerDirty={setComposerDirty} hideDraftWorkspace onApplyExample={(yaml, detached) => { setDraft(yaml); if (detached) setSelection(null); }} /></div>
     </div>
     <InspectCorrectWorkspace selection={selection} draft={draft} onDraft={setDraft} expanded={section === 'visualizer'} onExpandViewport={() => navigate('visualizer')} onReturnToEditor={() => navigate('environment')} onLoadExample={() => requestOpen(inspectionVersions[0])}>
      <p className="preview-historical-note">Historical Maple-table captures, not this draft. The suspended mug is a known scene defect; the sideways robot image is excluded. Origin job and exact immutable source are unavailable. No ovrtx render or physical success is claimed.</p>
      <AssetSceneVisualizer frames={visualizerFrames} draft={draft} sourceId={selection?.versionId ?? ''} />
     </InspectCorrectWorkspace>
    </section>
    <section hidden={section !== 'library'} aria-label="Library workspace"><LibraryPanel onOpen={requestOpen} opened={selection} localVersions={localVersions} /></section>
    {destinations.filter(d => !['environment', 'library', 'coverage', 'neo4j', 'jobs', 'visualizer'].includes(d.id)).map(d => visited.has(d.id) && <section key={d.id} hidden={section !== d.id} aria-label={`${d.label} workspace`}><WorkflowPanels section={d.id as Exclude<PreviewSection, 'environment' | 'library' | 'coverage' | 'neo4j' | 'jobs' | 'visualizer'>} context={context} /></section>)}

    {visited.has('neo4j') && <section hidden={section !== 'neo4j'} aria-label="Neo4j query workspace"><Neo4jQueryPreview /></section>}
    {visited.has('jobs') && <section hidden={section !== 'jobs'} aria-label="Jobs & diagnostics workspace"><JobsDiagnosticsPreview requestedJob={requestedJob} /></section>}
    {visited.has('coverage') && <section hidden={section !== 'coverage'} aria-label="Coverage workspace"><CoveragePanel onNavigate={navigate} /></section>}
   </main>
   <footer className="preview-footer">Cybernetic-Physics · Research workbench. Local interactions only; UI coverage is not runtime evidence. <span>All changes are discarded on reload.</span><TypographyLicenses /></footer>
  </div>
  {accountView && <ReviewDialog title={accountView === 'login' ? 'Login preview' : 'Sign up preview'} onClose={() => setAccountView(null)}>
   <p className="preview-tag">Account layout only · not connected</p>
   <p>No credentials are accepted or transmitted. Authentication and account creation are not implemented in this offline preview.</p>
   {accountView === 'signup' && <label className="preview-field">Display name<input disabled autoComplete="off" placeholder="Your name" /></label>}
   <label className="preview-field">Email<input type="email" disabled autoComplete="off" placeholder="name@example.invalid" /></label>
   <label className="preview-field">Password<input type="password" disabled autoComplete="off" placeholder="Unavailable in design preview" /></label>
   <div className="preview-actions"><button disabled>{accountView === 'login' ? 'Login unavailable in preview' : 'Signup unavailable in preview'}</button><button onClick={() => setAccountView(null)}>Close account preview</button></div>
  </ReviewDialog>}
  {pending && <ReviewDialog title="Replace unsaved workspace inputs?" onClose={() => setPending(null)}><p>The current draft, generation inputs or example review has changes. Opening another source does not alter that source or any run.</p><div className="preview-actions"><button onClick={() => setPending(null)}>Keep current draft</button><button onClick={() => { open(pending.kind === 'open' ? pending.selection : null); setPending(null); }}>Discard edits and continue</button></div></ReviewDialog>}
  {saveDraft !== null && <ReviewDialog title="Review example version save" onClose={() => setSaveDraft(null)}><p>Demonstrate the save → select → downstream review flow. This creates a local session example only. No files, research version numbers or graph intents are written.</p><label className="preview-field">Example version display name<input maxLength={100} value={saveName} onChange={e => setSaveName(e.target.value)} /></label><pre>{saveDraft}</pre><div className="preview-actions"><button disabled={!saveName.trim()} onClick={saveExample}>Create local example version</button><button onClick={() => setSaveDraft(null)}>Cancel save review</button></div></ReviewDialog>}
 </div>;
}
