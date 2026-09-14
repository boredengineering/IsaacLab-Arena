import { expect, expectTypeOf, it } from 'vitest';
import type { Graph, GraphEdge, GraphNode, JSONValue } from './editor-contracts';
import { createRendererDTOs, normalizeGraph, type JSONValue as DisplayJSONValue } from './graph-explorer/graph-model';
import { propertySummary } from './graph-explorer/graph-table';

it('accepts optional schema labels and JSON-valued API properties through normalized consumers', () => {
  const node: GraphNode = { id: 'a', label: 'A', role: 'object', properties: '[truncated]' };
  const labelled: GraphNode = { id: 'r', label: 'R', role: 'node', labels: ['ReifiedRelation'], properties: {} };
  const edge: GraphEdge = { id: 'e', source: 'a', target: 'r', label: 'participant', properties: '[truncated]' };
  const graph: Graph = { nodes: [node, labelled], edges: [edge] };
  const json: JSONValue = { scalar: 1, nested: [true, null, '[redacted]'] };
  expectTypeOf<JSONValue>().toEqualTypeOf<DisplayJSONValue>();
  expectTypeOf<GraphNode['properties']>().toEqualTypeOf<JSONValue>();
  expectTypeOf<GraphEdge['properties']>().toEqualTypeOf<JSONValue>();
  const normalized = normalizeGraph(graph);
  expect(normalized.nodes[0].properties).toBe('[truncated]');
  expect(normalized.nodes[1].labels).toEqual(['ReifiedRelation']);
  expect(propertySummary(edge.properties)).toBe('[truncated]');
  expect(propertySummary(json)).toBe('Object (2)');
  expect(JSON.parse(JSON.stringify(graph))).toEqual(graph);
  expect(createRendererDTOs(normalized).nodes[1].isReifier).toBe(true);
  expect(createRendererDTOs(normalized).links[0].source).toBe('a');
});

it('still normalizes unknown input rather than trusting compile-time contracts', () => {
  const malformed: unknown = { nodes: [{ id: 'a', label: 'A', role: 'object', properties: { bad: undefined } }], edges: [] };
  expect(normalizeGraph(malformed).diagnostics).toContainEqual({ code: 'invalid-properties', kind: 'node', index: 0, field: 'properties' });
  // @ts-expect-error API properties must be JSON, not arbitrary unknown objects.
  const invalid: GraphNode['properties'] = { bad: undefined };
  expect(normalizeGraph({ nodes: [{ id: 'a', label: 'A', role: 'object', properties: invalid }], edges: [] }).diagnostics).toHaveLength(1);
});
