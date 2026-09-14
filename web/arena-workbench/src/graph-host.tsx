import { Component, lazy, Suspense, type ReactNode } from 'react';
import type { Graph } from './editor-contracts';
import { GraphView } from './graph-view';

const Explorer = lazy(() => import('./graph-explorer/graph-explorer'));
export type GraphRendererChoice = 'legacy' | 'explorer';
export interface GraphRolloutProps {
  graphRenderer?: GraphRendererChoice;
  onGraphRendererChange?(renderer: GraphRendererChoice): void;
}
interface GraphHostProps {
  graph: Graph | null;
  scopeKey: string;
  revisionKey: string;
  label: string;
  sourceKind: 'authored' | 'persisted';
  visible?: boolean;
  renderer: GraphRendererChoice;
  onRendererChange(renderer: GraphRendererChoice): void;
}
export function parseGraphRenderer(value: unknown): GraphRendererChoice {
  return value === 'explorer' ? 'explorer' : 'legacy';
}
class ExplorerBoundary extends Component<{ children: ReactNode; visible: boolean }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed
      ? this.props.visible && <p role="alert">Graph explorer unavailable. Use the legacy graph control or preserve your draft before reloading to retry.</p>
      : this.props.children;
  }
}

/** Stable source-scoped controller host; the rollback control never depends on optional code. */
export function GraphHost({ renderer, onRendererChange, visible = true, ...props }: GraphHostProps) {
  return <div className="graph-host">
    {visible && <div className="graph-rollout">
      <span className="muted">{renderer === 'legacy' ? 'Legacy diagram' : 'Graph explorer preview · layout only'}</span>
      <button type="button" onClick={() => onRendererChange(renderer === 'legacy' ? 'explorer' : 'legacy')}>
        {renderer === 'legacy' ? 'Try graph explorer' : 'Use legacy graph'}
      </button>
    </div>}
    {renderer === 'legacy'
      ? visible && props.graph && <GraphView graph={props.graph} label={props.label} />
      : <ExplorerBoundary key={props.scopeKey} visible={visible}>
        <Suspense fallback={visible ? <p role="status">Loading graph explorer… The legacy view remains available.</p> : null}>
          <Explorer {...props} visible={visible} />
        </Suspense>
      </ExplorerBoundary>}
  </div>;
}
