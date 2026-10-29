import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { GraphView } from './graph-view';

it('wraps a large same-label result into readable columns rather than a microscopic vertical strip', () => {
  const graph = {
    nodes: Array.from({ length: 28 }, (_, index) => ({
      id: String(index), label: `Environment ${index}`, role: 'EnvironmentGraph', properties: {},
    })),
    edges: [],
  };
  render(<GraphView graph={graph} label="Result graph" />);
  const svg = screen.getByLabelText('Result graph', { exact: true });
  const positions = Array.from(svg.querySelectorAll('[data-node]')).map(node => node.getAttribute('transform'));
  const columns = new Set(positions.map(position => position?.match(/translate\(([^ ]+)/)?.[1]));
  expect(columns.size).toBeGreaterThan(1);
  const bounds = svg.getAttribute('viewBox')!.split(' ').map(Number);
  expect(bounds[3]).toBeLessThan(1000);
  expect(parseInt(svg.style.height)).toBeGreaterThan(360);
});
