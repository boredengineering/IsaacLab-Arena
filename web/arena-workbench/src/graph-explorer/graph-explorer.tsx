import { Component, Suspense, lazy, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { normalizeGraph, projectGraph, type GraphFilters, type GraphSelection } from './graph-model';
import { copyPresentation, createExplorerState, reconcileExplorerState, resetExplorerFilters, resetViewCamera, selectEntity, type ExplorerMode } from './explorer-state';
import { GraphTable, tabFocus } from './graph-table';
import { GraphInspector } from './graph-inspector';
import { roleColor } from './renderer-navigation';
import { samePresentation } from './presentation-equality';
import type { GraphPresentation, GraphRendererHandle } from './renderer-contracts';
import './graph-explorer.css';
const Graph2D = lazy(() => import('./graph-2d'));
const Graph3D = lazy(() => import('./graph-3d'));
export interface GraphExplorerProps { graph: unknown | null; scopeKey: string; revisionKey: string; label: string; visible?: boolean; sourceKind: 'authored' | 'persisted' }
class VisualBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <p role="alert">Graph renderer unavailable. Switch to Table or 2D. Preserve unsaved work before reloading to retry a failed module load.</p> : this.props.children; }
}
/** Stable, instance-scoped controller. Null data withholds inspection, not presentation intent. */
export default function GraphExplorer({ graph: input, scopeKey, revisionKey, label, visible = true, sourceKind }: GraphExplorerProps) {
  const graph = useMemo(() => input === null ? null : normalizeGraph(input), [input]);
  const [stored, setState] = useState(() => createExplorerState(scopeKey, revisionKey, graph, typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches));
  const state = reconcileExplorerState(stored, scopeKey, revisionKey, graph);
  if (state !== stored) setState(state);
  const projection = useMemo(() => graph ? projectGraph(graph, state.filters, state.selection) : null, [graph, state.filters, state.selection]);
  const [ready, setReady] = useState<{ token: object; handle: GraphRendererHandle } | null>(null);
  const [failure, setFailure] = useState<{ token: object; message: string } | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [focusRequest, setFocusRequest] = useState(0);
  const [step, setStep] = useState(10);
  const [labels, setLabels] = useState<'selected' | 'auto' | 'all'>('auto');
  const root = useRef<HTMLElement>(null), expandTrigger = useRef<HTMLButtonElement>(null), closeButton = useRef<HTMLButtonElement>(null);
  const id = useId();
  const mode = state.mode;
  // A changed capability token makes callbacks captured by retired renderers inert.
  const token = useMemo(() => ({}), [scopeKey, revisionKey, mode, visible, graph]);
  const currentToken = useRef(token); currentToken.current = token;
  const handle = ready?.token === token ? ready.handle : null;
  const rendererError = failure?.token === token ? failure.message : '';
  const liveContext = useRef({ scopeKey, graph }); liveContext.current = { scopeKey, graph };
  // Capture once at retirement, before adapter passive cleanup; never subscribe to force ticks.
  useLayoutEffect(() => () => {
    if (!handle || mode === 'table' || !graph || liveContext.current.scopeKey !== scopeKey) return;
    try {
      const snapshot = copyPresentation(handle.getSnapshot(), liveContext.current.graph ?? graph);
      setState(old => old.scopeKey === scopeKey && !samePresentation(old.snapshots[mode], snapshot) ? { ...old, snapshots: { ...old.snapshots, [mode]: snapshot } } : old);
    } catch { /* A failed/disposed visual keeps the last successful numeric snapshot. */ }
  }, [handle, mode, scopeKey, graph]);
  useEffect(() => {
    setReady(old => old && old.token !== token ? null : old);
    setFailure(old => old && old.token !== token ? null : old);
  }, [token]);
  const onReady = useCallback((next: GraphRendererHandle | null) => { if (currentToken.current === token) setReady(old => next ? old?.token === token && old.handle === next ? old : { token, handle: next } : null); }, [token]);
  const onSnapshot = useCallback((snapshot: GraphPresentation) => {
    if (currentToken.current !== token || mode === 'table' || !graph) return;
    const copied = copyPresentation(snapshot, graph);
    setState(old => old.scopeKey === scopeKey && !samePresentation(old.snapshots[mode], copied) ? { ...old, snapshots: { ...old.snapshots, [mode]: copied } } : old);
  }, [token, mode, scopeKey, graph]);
  const onSelect = useCallback((selection: GraphSelection) => { if (graph && currentToken.current === token) setState(old => selectEntity(old, graph, selection)); }, [graph, token]);
  const onError = useCallback((_message: string) => { if (currentToken.current === token) setFailure({ token, message: 'Graph renderer unavailable. Switch to Table or 2D.' }); }, [token]);
  useEffect(() => {
    if (!expanded || !visible || !root.current) return;
    const hidden: { element: Element; inert: string | null }[] = [];
    let current: Element | null = root.current;
    while (current?.parentElement) {
      for (const sibling of Array.from(current.parentElement.children)) {
        if (sibling === current) continue;
        hidden.push({ element: sibling, inert: sibling.getAttribute('inert') });
        sibling.setAttribute('inert', '');
      }
      current = current.parentElement;
      if (current === document.body) break;
    }
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeButton.current?.focus();
    return () => { for (const { element, inert } of hidden) { if (inert === null) element.removeAttribute('inert'); else element.setAttribute('inert', inert); } document.body.style.overflow = overflow; };
  }, [expanded, visible]);
  const changeFilters = (next: GraphFilters) => setState(old => ({ ...old, filters: next }));
  const changeMode = (next: ExplorerMode) => { setState(old => ({ ...old, mode: next })); setFailure(null); setReady(null); };
  const focusedVisualRequest = useRef(0);
  useEffect(() => {
    if (!focusRequest || focusedVisualRequest.current === focusRequest || !handle || !graph || !state.selection || !projection || projection.selectionStatus !== 'visible') return;
    focusedVisualRequest.current = focusRequest;
    const local = projectGraph(graph, { ...state.filters, matchesOnly: false, neighborhood: true }, state.selection);
    handle.fit(local.nodes.filter(node => projection.nodeIds.has(node.id)).map(node => node.id));
  }, [focusRequest, handle, graph, state.selection, state.filters, projection]);
  const focus = () => setFocusRequest(n => n + 1);
  const reveal = () => { if (graph) { setState(old => resetExplorerFilters(old, graph, true)); setFocusRequest(n => n + 1); } };
  const close = () => { setExpanded(false); queueMicrotask(() => expandTrigger.current?.focus()); };
  if (!visible) return null;
  const snapshot = state.snapshots[mode === '3d' ? '3d' : '2d'];
  const stress = !!graph && (graph.nodes.length > 512 || graph.edges.length > 1024);
  return <section ref={root} className={`graph-explorer${expanded ? ' graph-explorer-expanded' : ''}`} role={expanded ? 'dialog' : 'region'} aria-modal={expanded || undefined} aria-label={label} onKeyDown={event => {
    if (!expanded) return;
    if (event.key === 'Escape') { event.stopPropagation(); close(); }
    if (event.key === 'Tab') {
      const controls = Array.from(root.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), summary, [tabindex="0"]') ?? []).filter(element => !element.closest('[hidden]') && (!element.closest('details:not([open])') || element.tagName === 'SUMMARY'));
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  }}>
    <header className="graph-toolbar"><h3>{label}</h3><span>{sourceKind === 'authored' ? 'Authored YAML' : 'Persisted query result'} · Read-only layout</span><button ref={expandTrigger} type="button" hidden={expanded} onClick={() => setExpanded(true)}>Expand graph</button>{expanded && <button ref={closeButton} type="button" onClick={close}>Close expanded graph</button>}</header>
    <p>Relationship layout, not a physical 3D scene. Layout changes do not change YAML or scene poses.</p>
    <div role="tablist" aria-label="Graph display mode" onKeyDown={tabFocus}>{(['table', '2d', '3d'] as const).map(value => <button type="button" role="tab" key={value} id={`${id}-${value}`} aria-controls={`${id}-view`} aria-selected={mode === value} tabIndex={mode === value ? 0 : -1} onClick={() => changeMode(value)}>{value === 'table' ? 'Table' : value.toUpperCase()}</button>)}</div>
    {!graph || !projection ? <p role="status">Graph data withheld until a current valid result is available.</p> : <>
      <div className="graph-filters"><label>Search returned graph<input value={state.filters.search} maxLength={4096} onChange={event => changeFilters({ ...state.filters, search: event.target.value })} /></label><label><input type="checkbox" checked={state.filters.matchesOnly} onChange={event => changeFilters({ ...state.filters, matchesOnly: event.target.checked })} />Show matches only</label>
        <label><input type="checkbox" checked={state.filters.neighborhood} disabled={!state.selection} onChange={event => changeFilters({ ...state.filters, neighborhood: event.target.checked })} />Loaded neighbors</label>
        <button type="button" onClick={() => setState(old => resetExplorerFilters(old, graph))}>Clear filters</button>
        <details><summary>Node roles</summary>{[...new Set(graph.nodes.map(n => n.role))].sort().map(role => <label key={role}><input type="checkbox" aria-label={`Role ${role}`} checked={state.filters.allowedRoles.has(role)} onChange={event => { const allowedRoles = new Set(state.filters.allowedRoles); if (event.target.checked) allowedRoles.add(role); else allowedRoles.delete(role); changeFilters({ ...state.filters, allowedRoles }); }} />{role || '(empty role)'}</label>)}</details>
        <details><summary>Relationship types</summary>{[...new Set(graph.edges.map(e => e.label))].sort().map(type => <label key={type}><input type="checkbox" aria-label={`Type ${type}`} checked={state.filters.allowedTypes.has(type)} onChange={event => { const allowedTypes = new Set(state.filters.allowedTypes); if (event.target.checked) allowedTypes.add(type); else allowedTypes.delete(type); changeFilters({ ...state.filters, allowedTypes }); }} />{type || '(empty type)'}</label>)}</details>
      </div>
      <p role="status">Visible: {projection.counts.visibleNodes} / returned {projection.counts.returnedNodes} nodes · {projection.counts.visibleEdges} / returned {projection.counts.returnedEdges} relationships. Direct matches: {projection.counts.matchingNodes} nodes, {projection.counts.matchingEdges} relationships.</p>
      <ul className="graph-legend" aria-label="Node color legend">
        {[...new Set(graph.nodes.map(node => node.role))].sort().slice(0, 100).map(role => <li key={role}><span data-role-color aria-hidden="true" style={{ backgroundColor: roleColor(role) }} />{role || '(empty role)'}</li>)}
        <li>Diamonds / R: explicit reifiers · yellow: selection or neighbors</li>
        {new Set(graph.nodes.map(node => node.role)).size > 100 && <li>Legend limited to the first 100 roles; use role filters to inspect categories.</li>}
      </ul>
      {state.filters.search && <details open><summary>Search matches in currently allowed roles/types ({projection.matches.length}{projection.matchesTruncated ? ', bounded list' : ''})</summary><ul className="graph-matches">{projection.matches.map(match => <li key={JSON.stringify([match.kind, match.id])}><button type="button" onClick={() => onSelect(match)}>{match.kind}: {(match.kind === 'node' ? graph.nodeById.get(match.id) : graph.edgeById.get(match.id))?.label} · {match.id}</button></li>)}</ul><p>Visible entities include induced endpoint context, not only direct text matches.</p></details>}
      {!!graph.diagnostics.length && <details className="graph-diagnostics"><summary>Projection diagnostics: {graph.diagnostics.length} · quarantined {graph.quarantined.nodes} nodes, {graph.quarantined.edges} relationships</summary><ul>{graph.diagnostics.slice(0, 100).map((d, i) => <li key={i}>{d.kind}: {d.code}{d.index === undefined ? '' : ` at index ${d.index}`}{d.field ? ` (${d.field})` : ''}</li>)}</ul>{graph.diagnostics.length > 100 && <p>Showing the first 100 diagnostics.</p>}</details>}
      <div className="graph-toolbar"><button type="button" disabled={mode !== 'table' && !handle} onClick={() => handle?.fit()}>Fit visible</button><button type="button" disabled={!state.selection || projection.selectionStatus !== 'visible'} onClick={focus}>Focus selection</button><button type="button" disabled={!state.selection} onClick={() => onSelect(null)}>Clear selection</button></div>
      <div className="graph-toolbar">
        <button type="button" disabled={mode === 'table' || !handle} onClick={() => handle?.zoom(0.8)}>Zoom out</button>
        <button type="button" disabled={mode === 'table' || !handle} onClick={() => handle?.zoom(1.25)}>Zoom in</button>
        <button type="button" disabled={mode === 'table' || !handle} onClick={() => handle?.setFrozen(!snapshot.frozen)}>{snapshot.frozen ? 'Resume layout' : 'Freeze layout'}</button>
        <button type="button" disabled={mode === 'table' || !handle} onClick={() => handle?.unpinAll()}>Unpin all</button>
        <button type="button" disabled={mode === 'table' || !handle} onClick={() => handle?.reset()}>Reset layout</button>
        <label>Label density <select value={labels} onChange={event => setLabels(event.target.value as typeof labels)}><option value="selected">Selected</option><option value="auto">Auto</option><option value="all">All</option></select></label>
        <span>{snapshot.pins.size} pinned · {snapshot.frozen ? 'Frozen' : 'Live'}</span>
      </div>
      <details open><summary>Navigation controls</summary><fieldset disabled={mode === 'table' || !handle}><legend>Camera navigation (view-relative)</legend>
        <label>Navigation step <select value={step} onChange={event => setStep(Number(event.target.value))}>{[1, 10, 50].map(value => <option key={value} value={value}>{value} layout units / {value}° orbit</option>)}</select></label>
        <div className="graph-toolbar"><button type="button" onClick={() => handle?.pan(-step, 0)}>Pan left</button><button type="button" onClick={() => handle?.pan(step, 0)}>Pan right</button><button type="button" onClick={() => handle?.pan(0, -step)}>Pan up</button><button type="button" onClick={() => handle?.pan(0, step)}>Pan down</button>
          {mode === '3d' && <><button type="button" onClick={() => handle?.orbit(-step * Math.PI / 180, 0)}>Orbit left</button><button type="button" onClick={() => handle?.orbit(step * Math.PI / 180, 0)}>Orbit right</button><button type="button" onClick={() => handle?.orbit(0, step * Math.PI / 180)}>Orbit up</button><button type="button" onClick={() => handle?.orbit(0, -step * Math.PI / 180)}>Orbit down</button></>}
          <button type="button" onClick={() => { if (handle) resetViewCamera(handle, mode); }}>Reset camera</button>
        </div><p>2D: drag background to pan. 3D: drag background to orbit; secondary drag pans. Dragged nodes move in the view plane and become pinned. Buttons provide non-drag alternatives.</p>
      </fieldset></details>
      <div className="graph-workspace"><div role="tabpanel" id={`${id}-view`} aria-labelledby={`${id}-${mode}`}>
        {!graph.nodes.length ? <p>{graph.diagnostics.length ? 'No valid graph entities are available. Review projection diagnostics.' : 'No returned graph entities. Raw query rows, if any, remain separate.'}</p> : !projection.nodes.length && <p>No filter matches. Clear filters to show returned entities.</p>}
        <div hidden={mode !== 'table'}><GraphTable presentation={state.table} onPresentationChange={action => setState(old => ({ ...old, table: typeof action === 'function' ? action(old.table) : action }))} graph={graph} projection={projection} selection={state.selection} onSelect={onSelect} focusRequest={focusRequest} /></div>
        {mode !== 'table' && (stress ? <p role="status">Visualization limit: this graph exceeds 512 nodes or 1,024 relationships. No entities were silently dropped. Choose Table to inspect all valid returned entities.</p> : <div className="graph-visual-area"><VisualBoundary key={`${scopeKey}:${mode}:${revisionKey}`}><Suspense fallback={<p role="status">Loading {mode.toUpperCase()} renderer. Table remains available.</p>}>{rendererError ? <p role="alert">{rendererError}</p> : (() => { const Renderer = mode === '3d' ? Graph3D : Graph2D; return <Renderer graph={graph} projection={projection} scopeKey={scopeKey} snapshot={snapshot} selection={state.selection} labels={labels} onSelect={onSelect} onReady={onReady} onSnapshot={onSnapshot} onError={onError} />; })()}</Suspense></VisualBoundary></div>)}
      </div><GraphInspector graph={graph} selection={state.selection} onSelect={onSelect} hidden={projection.selectionStatus === 'hidden'} onReveal={reveal} mode={mode} handle={handle} snapshot={snapshot} step={step} /></div>
      <p aria-live="polite">{state.announcement}</p>
    </>}
  </section>;
}
