import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type Dispatch, type SetStateAction } from 'react';
import { flexRender, getCoreRowModel, getPaginationRowModel, getSortedRowModel, useReactTable, type ColumnDef, type PaginationState, type SortingState } from '@tanstack/react-table';
import { createTableState, type ExplorerTableState } from './explorer-state';
import type { GraphProjection, GraphSelection, JSONValue, NormalizedGraph } from './graph-model';
export function propertySummary(value: JSONValue): string {
  if (value === null) return 'null';
  if (Array.isArray(value)) return `Array (${value.length})`;
  if (typeof value === 'object') return `Object (${Object.keys(value).length})`;
  return String(value).slice(0, 120);
}
/** Manual activation: arrows move focus, only Enter/Space/click selects a tab. */
export function tabFocus(event: KeyboardEvent<HTMLElement>) {
  const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
  const index = tabs.indexOf(document.activeElement as HTMLButtonElement);
  let next = index;
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % tabs.length;
  else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index + tabs.length - 1) % tabs.length;
  else if (event.key === 'Home') next = 0;
  else if (event.key === 'End') next = tabs.length - 1;
  else return;
  event.preventDefault(); tabs[next]?.focus();
}
interface EntityRow { id: string; label: string; role: string; source: string; target: string; count: number; properties: JSONValue }
export interface GraphTableProps {
  graph: NormalizedGraph; projection: GraphProjection; selection: GraphSelection;
  onSelect(selection: GraphSelection): void; focusRequest?: number;
  presentation?: ExplorerTableState; onPresentationChange?: Dispatch<SetStateAction<ExplorerTableState>>;
}
export function GraphTable({ graph, projection, selection, onSelect, focusRequest = 0, presentation, onPresentationChange }: GraphTableProps) {
  const id = useId();
  const [local, setLocal] = useState(createTableState);
  const { kind, sorting, pagination } = presentation ?? local;
  const update = onPresentationChange ?? setLocal;
  const setKind = (kind: 'node' | 'edge') => update(old => ({ ...old, kind }));
  const setSorting = (action: SetStateAction<SortingState>) => update(old => ({ ...old, sorting: typeof action === 'function' ? action(old.sorting) : action }));
  const setPagination = (action: SetStateAction<PaginationState>) => update(old => ({ ...old, pagination: typeof action === 'function' ? action(old.pagination) : action }));
  const data = useMemo<EntityRow[]>(() => kind === 'node'
    ? projection.nodes.map(n => ({ ...n, count: graph.incidentEdges.get(n.id)?.length ?? 0, source: '', target: '' }))
    : projection.edges.map(e => ({ ...e, role: '', count: 0 })), [kind, projection, graph]);
  const columns = useMemo<ColumnDef<EntityRow>[]>(() => {
    const endpoint = (endpointId: string) => <button type="button" onClick={() => onSelect({ kind: 'node', id: endpointId })}>{graph.nodeById.get(endpointId)?.label} · {endpointId}</button>;
    return [
      { accessorKey: 'label', header: kind === 'node' ? 'Label' : 'Type' },
      { accessorKey: 'id', header: 'Full ID' },
      ...(kind === 'node' ? [{ accessorKey: 'role', header: 'Role' }, { accessorKey: 'count', header: 'Loaded relationships' }] : [
        { accessorKey: 'source', header: 'Source →', cell: ({ row }: { row: { original: EntityRow } }) => endpoint(row.original.source) },
        { accessorKey: 'target', header: '→ Target', cell: ({ row }: { row: { original: EntityRow } }) => endpoint(row.original.target) },
      ]),
      { id: 'properties', header: 'Properties', accessorFn: row => propertySummary(row.properties), enableSorting: false },
      { id: 'inspect', header: 'Inspect', enableSorting: false, cell: ({ row }) => <button type="button" aria-label={`Inspect ${kind === 'node' ? 'node' : 'relationship'} ${row.original.id}`} onClick={() => onSelect({ kind, id: row.original.id })}>Inspect</button> },
    ];
  }, [kind, graph, onSelect]);
  const table = useReactTable({ data, columns, autoResetPageIndex: false, state: { sorting, pagination }, getRowId: row => row.id,
    onSortingChange: update => setSorting(old => { const next = typeof update === 'function' ? update(old) : update; return next.some(s => s.id === 'id') ? next : [...next, { id: 'id', desc: false }]; }),
    onPaginationChange: setPagination, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(), getPaginationRowModel: getPaginationRowModel() });
  const focusedRequest = useRef(0);
  useEffect(() => {
    const maxPage = Math.max(0, Math.ceil(data.length / pagination.pageSize) - 1);
    if (pagination.pageIndex > maxPage) setPagination(old => ({ ...old, pageIndex: maxPage }));
  }, [data.length, pagination.pageIndex, pagination.pageSize]);
  useEffect(() => {
    if (!focusRequest || focusedRequest.current === focusRequest || !selection) return;
    if (selection.kind !== kind) { setKind(selection.kind); return; }
    focusedRequest.current = focusRequest;
    const index = table.getSortedRowModel().rows.findIndex(row => row.id === selection.id);
    if (index >= 0) setPagination(old => ({ ...old, pageIndex: Math.floor(index / old.pageSize) }));
  }, [focusRequest, selection, kind, table]);
  return <section aria-label="Graph entities">
    <div role="tablist" aria-label="Graph entity kind" onKeyDown={tabFocus}>{(['node', 'edge'] as const).map(value => <button type="button" key={value} role="tab" id={`${id}-${value}`} aria-controls={`${id}-panel`} aria-selected={kind === value} tabIndex={kind === value ? 0 : -1} onClick={() => { setKind(value); setPagination(p => ({ ...p, pageIndex: 0 })); }}>{value === 'node' ? 'Nodes' : 'Relationships'}</button>)}</div>
    <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${kind}`} className="graph-table-scroll">
      <table><caption>Graph entities · {kind === 'node' ? 'Nodes' : 'Relationships'} · returned data only</caption><thead>{table.getHeaderGroups().map(group => <tr key={group.id}>{group.headers.map(header => <th key={header.id} scope="col" aria-sort={header.column.getIsSorted() === 'asc' ? 'ascending' : header.column.getIsSorted() === 'desc' ? 'descending' : undefined}>{header.column.getCanSort() ? <button type="button" onClick={header.column.getToggleSortingHandler()}>{flexRender(header.column.columnDef.header, header.getContext())}</button> : flexRender(header.column.columnDef.header, header.getContext())}</th>)}</tr>)}</thead>
        <tbody>{table.getRowModel().rows.map(row => <tr key={row.id} data-selected={selection?.kind === kind && selection.id === row.id} onClick={event => { if (!(event.target as HTMLElement).closest('button')) onSelect({ kind, id: row.id }); }}>{row.getVisibleCells().map(cell => <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}</tr>)}</tbody>
      </table>
    </div>
    <div className="graph-toolbar"><span>{data.length} visible rows · {table.getRowModel().rows.length} page rows · Page {pagination.pageIndex + 1} of {Math.max(1, table.getPageCount())}</span>
      <button type="button" disabled={!table.getCanPreviousPage()} onClick={() => table.previousPage()}>Previous page</button><button type="button" disabled={!table.getCanNextPage()} onClick={() => table.nextPage()}>Next page</button>
      <label>Rows per page <select value={pagination.pageSize} onChange={event => table.setPageSize(Number(event.target.value))}>{[25, 50, 100].map(size => <option key={size}>{size}</option>)}</select></label>
    </div>
  </section>;
}
