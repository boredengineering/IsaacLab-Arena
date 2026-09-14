import { useEffect, useState } from 'react';
import { isReifier, type GraphSelection, type NormalizedGraph } from './graph-model';
import type { ExplorerMode } from './explorer-state';
import type { GraphPresentation, GraphRendererHandle } from './renderer-contracts';
import { PropertyTree } from './property-tree';
export interface GraphInspectorProps {
  graph: NormalizedGraph; selection: GraphSelection; onSelect(selection: GraphSelection): void;
  hidden: boolean; onReveal(): void; mode: ExplorerMode; handle: GraphRendererHandle | null;
  snapshot: GraphPresentation; step: number;
}
export function GraphInspector(props: GraphInspectorProps) {
  return <aside className="graph-inspector" aria-label="Selection inspector">{props.selection
    ? <EntityInspector key={JSON.stringify([props.selection.kind, props.selection.id])} {...props} />
    : <p>Select a node or relationship using Table, search, or the graph.</p>}</aside>;
}
function EntityInspector({ graph, selection, onSelect, hidden, onReveal, mode, handle, snapshot, step }: GraphInspectorProps) {
  const node = selection?.kind === 'node' ? graph.nodeById.get(selection.id) : undefined;
  const edge = selection?.kind === 'edge' ? graph.edgeById.get(selection.id) : undefined;
  const entity = node ?? edge;
  const [page, setPage] = useState(0);
  const [copyStatus, setCopyStatus] = useState('');
  const [error, setError] = useState('');
  const position = node ? snapshot.positions.get(node.id) : undefined;
  const [coordinates, setCoordinates] = useState({ x: String(position?.x ?? 0), y: String(position?.y ?? 0), z: String(position?.z ?? 0) });
  useEffect(() => { setCoordinates({ x: String(position?.x ?? 0), y: String(position?.y ?? 0), z: String(position?.z ?? 0) }); }, [position?.x, position?.y, position?.z, mode]);
  if (!entity) return <p>Selection is no longer available.</p>;
  const edges = node ? graph.incidentEdges.get(node.id) ?? [] : [];
  const currentPage = Math.min(page, Math.max(0, Math.ceil(edges.length / 25) - 1));
  const canMove = !!handle && mode !== 'table';
  async function copyId() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(entity!.id); setCopyStatus('ID copied.');
    } catch { setCopyStatus('Clipboard unavailable. Select and copy the full ID below.'); }
  }
  return <>
    <h3>{node ? 'Node' : 'Relationship'}: {entity.label}</h3>
    <code className="graph-full-id">{entity.id}</code><button type="button" onClick={() => void copyId()}>Copy ID</button><p role="status">{copyStatus}</p>
    {hidden && <p><strong>Hidden by filters</strong> <button type="button" onClick={onReveal}>Reveal (clear filters)</button></p>}
    {node && <p>Role: {node.role}{node.labels?.length ? ` · Labels: ${node.labels.join(', ')}` : ''}{isReifier(node) ? ' · Reifier' : ''}</p>}
    {edge && <div className="graph-endpoints"><p>Type: {edge.label}</p><button type="button" onClick={() => onSelect({ kind: 'node', id: edge.source })}>Source: {graph.nodeById.get(edge.source)?.label} · {edge.source}</button><span aria-hidden="true"> → </span><button type="button" onClick={() => onSelect({ kind: 'node', id: edge.target })}>Target: {graph.nodeById.get(edge.target)?.label} · {edge.target}</button>{edge.source === edge.target && <p>Self-loop constraint</p>}</div>}
    <PropertyTree key={JSON.stringify([selection!.kind, entity.id])} value={entity.properties} />
    {node && <>
      <h4>Loaded relationships ({edges.length})</h4>
      <ul>{edges.slice(currentPage * 25, currentPage * 25 + 25).map(related => <li key={related.id}><button type="button" aria-label={`Inspect relationship ${related.id}`} onClick={() => onSelect({ kind: 'edge', id: related.id })}>{related.label} · {related.source} → {related.target} · {related.id}</button></li>)}</ul>
      {edges.length > 25 && <div><button type="button" aria-label="Previous loaded relationships" disabled={!currentPage} onClick={() => setPage(currentPage - 1)}>Previous</button><span>Page {currentPage + 1} / {Math.ceil(edges.length / 25)}</span><button type="button" aria-label="Next loaded relationships" disabled={(currentPage + 1) * 25 >= edges.length} onClick={() => setPage(currentPage + 1)}>Next</button></div>}
      <fieldset disabled={!canMove}><legend>Reposition layout node</legend>
        <p>Graph-layout units, not scene meters. Moving pins this node.</p>
        <p>{snapshot.pins.has(node.id) ? 'Pinned' : 'Unpinned'} · {snapshot.frozen ? 'Layout frozen' : 'Layout live'}</p>
        <button type="button" onClick={() => handle?.setPinned(node.id, !snapshot.pins.has(node.id))}>{snapshot.pins.has(node.id) ? 'Unpin selected' : 'Pin selected'}</button>
        {(['x', 'y', ...(mode === '3d' ? ['z'] : [])] as ('x' | 'y' | 'z')[]).map(axis => <label key={axis}>Layout {axis.toUpperCase()}<input inputMode="decimal" value={coordinates[axis]} onChange={event => setCoordinates(old => ({ ...old, [axis]: event.target.value }))} /></label>)}
        <button type="button" onClick={() => {
          const values = { x: Number(coordinates.x), y: Number(coordinates.y), z: mode === '3d' ? Number(coordinates.z) : 0 };
          if (!coordinates.x.trim() || !coordinates.y.trim() || (mode === '3d' && !coordinates.z.trim()) || !Object.values(values).every(Number.isFinite)) { setError('Enter finite numeric coordinates for every axis.'); return; }
          setError(''); handle?.moveNode(node.id, values);
        }}>Apply coordinates</button>
        {error && <p role="alert">{error}</p>}
        <div className="graph-toolbar">{[['left', -step, 0, 0], ['right', step, 0, 0], ['up', 0, -step, 0], ['down', 0, step, 0], ...(mode === '3d' ? [['forward', 0, 0, step], ['backward', 0, 0, -step]] : [])].map(([label, dx, dy, dz]) => <button type="button" key={label} onClick={() => handle?.nudgeNode(node.id, Number(dx), Number(dy), Number(dz))}>Nudge {label} (view-relative)</button>)}</div>
      </fieldset>
    </>}
  </>;
}
