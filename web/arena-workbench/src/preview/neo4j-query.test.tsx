import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { Neo4jQueryPreview } from './neo4j-query';

afterEach(cleanup);
const change = (name: string, value: string) => fireEvent.change(screen.getByLabelText(name), { target: { value } });
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));

describe('offline Neo4j query preview', () => {
  it('offers a labelled fixture graph with pointer and keyboard inspection, retained across format changes', () => {
    render(<Neo4jQueryPreview />);
    click('Load example fixture');
    click('Graph');
    expect(screen.getByRole('group', { name: 'Example Neo4j graph' })).toHaveTextContent('USES');
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.getByRole('region', { name: 'Example node inspector' })).toHaveTextContent('Select an example node');
    click('Inspect Example tabletop');
    expect(screen.getByRole('region', { name: 'Example node inspector' })).toHaveTextContent('example-environment');
    fireEvent.keyDown(screen.getByRole('button', { name: 'Inspect Example G1' }), { key: 'Enter' });
    expect(screen.getByRole('region', { name: 'Example node inspector' })).toHaveTextContent('example-robot');
    click('Table');
    expect(screen.getByRole('table', { name: 'Example Neo4j rows' })).toBeInTheDocument();
    click('Graph');
    expect(screen.getByRole('button', { name: 'Inspect Example G1' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.keyDown(screen.getByRole('button', { name: 'Inspect Example tabletop' }), { key: ' ' });
    expect(screen.getByRole('region', { name: 'Example node inspector' })).toHaveTextContent('example-environment');
    change('Cypher query', 'RETURN 1');
    expect(screen.getByText(/Fixture is stale/)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Example node inspector' })).toHaveTextContent('example-environment');
    change('Query example', 'truncated');
    click('Load example fixture');
    click('Graph');
    expect(screen.getByRole('region', { name: 'Example node inspector' })).toHaveTextContent('Select an example node');
    expect(fetch).not.toHaveBeenCalled();
  });
  it('does not retain graph nodes when an empty or error fixture replaces them', () => {
    render(<Neo4jQueryPreview />);
    click('Load example fixture');
    click('Graph');
    click('Inspect Example G1');
    for (const choice of ['empty', 'error']) {
      change('Query example', choice);
      click('Load example fixture');
      expect(screen.queryByRole('group', { name: 'Example Neo4j graph' })).toBeNull();
      expect(screen.queryByRole('region', { name: 'Example node inspector' })).toBeNull();
    }
  });
  it('loads fixtures separately from review and withholds them for custom query or parameter values', () => {
    render(<Neo4jQueryPreview />);
    const query = (screen.getByLabelText('Cypher query') as HTMLTextAreaElement).value;
    const params = (screen.getByLabelText('Parameters (JSON object)') as HTMLTextAreaElement).value;
    expect(screen.getByText(/No fixture loaded/)).toBeInTheDocument();
    click('Review query locally');
    expect(screen.getByText(/No fixture loaded/)).toBeInTheDocument();
    click('Load example fixture');
    expect(screen.getByRole('table', { name: 'Example Neo4j rows' })).toHaveTextContent('Example tabletop');
    change('Cypher query', 'RETURN 123');
    expect(screen.getByText(/Fixture is stale/)).toBeInTheDocument();
    expect(screen.getByText(/Custom-query results unavailable/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Load example fixture' })).toBeDisabled();
    change('Cypher query', query);
    change('Parameters (JSON object)', '{"name":"custom"}');
    expect(screen.getByRole('button', { name: 'Load example fixture' })).toBeDisabled();
    change('Parameters (JSON object)', '{"name":"Example tabletop","extra":true}');
    expect(screen.getByRole('button', { name: 'Load example fixture' })).toBeDisabled();
    change('Parameters (JSON object)', params);
    expect(screen.getByRole('button', { name: 'Load example fixture' })).toBeEnabled();
    expect(fetch).not.toHaveBeenCalled();
  });
  it.each([
    ['empty', 'Empty fixture — 0 example rows.'],
    ['error', 'Error fixture — illustrative database unavailable; no request was made.'],
    ['truncated', 'Truncated fixture — 1 example row shown; additional rows intentionally omitted.'],
  ])('loads only the explicitly selected %s fixture', (choice, message) => {
    render(<Neo4jQueryPreview />);
    click('Review query locally');
    const frozen = screen.getByTestId('frozen-query-review').textContent;
    change('Query example', choice);
    expect(screen.getByText(/No fixture loaded/)).toBeInTheDocument();
    expect(screen.getByTestId('frozen-query-review').textContent).toBe(frozen);
    click('Load example fixture');
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(screen.getByText(/Fixture only — not executed query results/)).toBeInTheDocument();
    if (choice !== 'truncated') expect(screen.queryByRole('table')).toBeNull();
  });
  it.each(['unverified', 'available', 'unavailable', 'session-expired'])('keeps %s connection examples illustrative and independent of review', choice => {
    render(<Neo4jQueryPreview />);
    change('Connection-state example', choice);
    expect(screen.getByRole('status', { name: 'Connection example status' })).toHaveTextContent(`${choice} example only`);
    click('Review query locally');
    expect(screen.getByTestId('frozen-query-review')).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /connect|publish|run query/i })).toBeNull();
  });
  it.each(['{', 'null', '[]', '42', '"text"', '{"n":1e400}', '{"nested":[{"n":-1e400}]}'])('rejects invalid JSON-object parameters: %s', value => {
    render(<Neo4jQueryPreview />);
    change('Parameters (JSON object)', value);
    expect(screen.getByRole('alert')).toHaveTextContent(/Parameters must be a JSON object with finite numbers/);
    expect(screen.getByRole('button', { name: 'Review query locally' })).toBeDisabled();
    expect(screen.queryByTestId('frozen-query-review')).toBeNull();
  });
  it('accepts nested finite JSON and blocks blank Cypher', () => {
    render(<Neo4jQueryPreview />);
    const params = { nested: [null, true, { n: 3.5, text: 'Infinity' }] };
    change('Parameters (JSON object)', JSON.stringify(params));
    change('Cypher query', '   ');
    expect(screen.getByRole('button', { name: 'Review query locally' })).toBeDisabled();
    change('Cypher query', 'RETURN $nested');
    click('Review query locally');
    expect(JSON.parse(screen.getByTestId('frozen-query-review').textContent!).params).toEqual(params);
    change('Parameters (JSON object)', '{');
    expect(JSON.parse(screen.getByTestId('frozen-query-review').textContent!).params).toEqual(params);
  });
  it('freezes explicit query reviews without executing or overwriting them after edits', () => {
    render(<Neo4jQueryPreview />);
    expect(screen.getByText(/No database connection/)).toBeInTheDocument();
    click('Review query locally');
    const frozen = screen.getByTestId('frozen-query-review').textContent;
    expect(JSON.parse(frozen!)).toMatchObject({ exampleOnly: true, executed: false });
    expect(screen.queryByRole('table')).toBeNull();
    change('Cypher query', 'RETURN $value');
    change('Parameters (JSON object)', '{"value":42}');
    expect(screen.getByText(/Review is stale/)).toBeInTheDocument();
    expect(screen.getByTestId('frozen-query-review').textContent).toBe(frozen);
    expect(screen.getByRole('button', { name: 'Review query locally' })).toBeDisabled();
    click('Clear query review');
    click('Review query locally');
    expect(JSON.parse(screen.getByTestId('frozen-query-review').textContent!)).toMatchObject({ query: 'RETURN $value', params: { value: 42 }, executed: false });
  });
});
