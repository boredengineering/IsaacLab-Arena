import { useId, useMemo, useRef, useState } from 'react';
import type { Graph } from './editor-contracts';
/** Interactive diagram of server-returned nodes only; layout has no semantic authority. */
export function GraphView({ graph, label }: { graph: Graph; label: string }) {
  const marker = useId().replaceAll(':', '');
  const [selected, setSelected] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const columns = Math.min(4, Math.max(1, Math.ceil(Math.sqrt(graph.nodes.length))));
  const layout = useMemo(() => new Map(
    graph.nodes.map((node, index) => [node.id, {
      x: 135 + (index % columns) * 240,
      y: 75 + Math.floor(index / columns) * 95,
    }]),
  ), [graph, columns]);
  const width = Math.max(720, 270 + (columns - 1) * 240);
  const height = Math.max(360, ...[...layout.values()].map((p) => p.y + 70));
  const node = graph.nodes.find((n) => n.id === selected);
  return (
    <div className="graph-view">
      <div className="graph-toolbar">
        <span>
          {graph.nodes.length} nodes · {graph.edges.length} edges
        </span>
        <div className="actions">
          <button
            aria-label={`Zoom out ${label}`}
            onClick={() => setZoom((z) => Math.max(0.4, z / 1.2))}
          >
            −
          </button>
          <button
            aria-label={`Zoom in ${label}`}
            onClick={() => setZoom((z) => Math.min(12, z * 1.2))}
          >
            +
          </button>
          <button
            onClick={() => {
              setZoom(1);
              setOffset({ x: 0, y: 0 });
            }}
          >
            Fit graph
          </button>
        </div>
      </div>
      {graph.nodes.length ? (
        <svg
          className="spatial-graph"
          style={{ height: Math.min(720, height) }}
          aria-label={label}
          viewBox={`0 0 ${width} ${height}`}
          onPointerDown={(e) => {
            if ((e.target as Element).closest('[data-node]')) return;
            const box = e.currentTarget.getBoundingClientRect();
            drag.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y };
            e.currentTarget.setPointerCapture(e.pointerId);
            void box;
          }}
          onPointerMove={(e) => {
            if (drag.current) {
              const box = e.currentTarget.getBoundingClientRect();
              setOffset({
                x: drag.current.ox + ((e.clientX - drag.current.x) * width) / box.width,
                y: drag.current.oy + ((e.clientY - drag.current.y) * height) / box.height,
              });
            }
          }}
          onPointerUp={() => {
            drag.current = null;
          }}
          onPointerCancel={() => {
            drag.current = null;
          }}
        >
          <defs>
            <marker id={marker} markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
              <path d="M0 0 L7 3.5 L0 7" fill="#81938d" />
            </marker>
          </defs>
          <g transform={`translate(${offset.x} ${offset.y}) scale(${zoom})`}>
            {graph.edges.map((edge, i) => {
              const a = layout.get(edge.source),
                b = layout.get(edge.target);
              if (!a || !b) return null;
              const middle = (a.y + b.y) / 2 - 18 - (i % 3) * 12;
              return (
                <g key={edge.id}>
                  <path
                    d={
                      a === b
                        ? `M ${a.x + 70} ${a.y} C ${a.x + 155} ${a.y - 80}, ${a.x - 155} ${a.y - 80}, ${a.x - 70} ${a.y}`
                        : `M ${a.x} ${a.y} Q ${(a.x + b.x) / 2} ${middle} ${b.x} ${b.y}`
                    }
                    fill="none"
                    stroke="#a4b2ad"
                    strokeWidth="1.5"
                    markerEnd={`url(#${marker})`}
                  />
                  <text
                    className="edge-label"
                    x={(a.x + b.x) / 2}
                    y={middle - 7}
                    textAnchor="middle"
                  >
                    {edge.label}
                    <title>{JSON.stringify(edge.properties)}</title>
                  </text>
                </g>
              );
            })}
            {graph.nodes.map((n) => {
              const p = layout.get(n.id)!;
              const reifier = /reifi/i.test(n.role);
              return (
                <g
                  key={n.id}
                  data-node={n.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`Inspect ${n.label}`}
                  onClick={() => setSelected(n.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      setSelected(n.id);
                    }
                  }}
                  className={`graph-node ${selected === n.id ? 'is-selected' : ''}`}
                  transform={`translate(${p.x} ${p.y})`}
                >
                  {reifier ? (
                    <path d="M0 -32 L100 0 L0 32 L-100 0 Z" className="reifier" />
                  ) : (
                    <rect x="-104" y="-27" width="208" height="54" rx="7" />
                  )}
                  <text textAnchor="middle" y="-2">
                    {n.label.length > 25 ? `${n.label.slice(0, 23)}…` : n.label}
                  </text>
                  <text className="node-role" textAnchor="middle" y="16">
                    {n.role}
                  </text>
                  <title>{n.label}</title>
                </g>
              );
            })}
          </g>
        </svg>
      ) : (
        <div className="empty-state">
          No graph nodes returned. Validate an environment or run a query.
        </div>
      )}
      <div className="graph-caption">
        Drag to pan · select a node to inspect · diamonds are explicit reifiers
      </div>
      {node && (
        <section className="node-inspector">
          <div className="section-heading">
            <h3>Node inspector</h3>
            <button className="quiet" onClick={() => setSelected(null)}>
              Close inspector
            </button>
          </div>
          <strong>{node.label}</strong>
          <p className="muted">
            {node.id} · {node.role}
          </p>
          <pre>{JSON.stringify(node.properties, null, 2)}</pre>
          <details>
            <summary>Connected edges</summary>
            <pre>
              {JSON.stringify(
                graph.edges.filter((e) => e.source === node.id || e.target === node.id),
                null,
                2,
              )}
            </pre>
          </details>
        </section>
      )}
    </div>
  );
}
