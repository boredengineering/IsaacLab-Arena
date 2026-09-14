import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRuntime } from './runtime';
import { PropertyTree } from './graph-explorer/property-tree';

const record = (value: unknown): Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown) => typeof value === 'string' ? value : 'Not provided';
const categories = ['embodiments', 'backgrounds', 'objects', 'relations', 'tasks'] as const;
type Category = typeof categories[number];
function RegistryTable({ value }: { value: unknown }) {
  const [category, setCategory] = useState<Category>('embodiments');
  const [filter, setFilter] = useState('');
  const [page, setPage] = useState(0);
  const catalogues = record(record(value).catalogues);
  const source = category === 'relations' || category === 'tasks' ? record(catalogues[category])[category] : record(catalogues.assets)[category];
  const rows = Array.isArray(source) ? source : [];
  const needle = filter.toLowerCase();
  const matches = rows.filter(item => {
    const row = record(item);
    const fields = [row.name, row.summary, ...(Array.isArray(row.tags) ? row.tags : []), ...(Array.isArray(row.required_params) ? row.required_params : [])];
    return !needle || fields.some(field => typeof field === 'string' && field.toLowerCase().includes(needle));
  });
  const current = Math.min(page, Math.max(0, Math.ceil(matches.length / 25) - 1));
  return <>
    <label>Registry category <select value={category} onChange={event => { setCategory(event.target.value as Category); setPage(0); }}>{categories.map(name => <option key={name}>{name}</option>)}</select></label>
    <label>Filter registries <input value={filter} onChange={event => { setFilter(event.target.value); setPage(0); }} /></label>
    <p role="status">{matches.length} matching / {rows.length} collected entries</p>
    <table><caption>Registered {category}</caption><thead><tr><th scope="col">Name</th><th scope="col">{category === 'relations' ? 'Arity' : category === 'tasks' ? 'Required parameters' : 'Tags'}</th><th scope="col">Summary</th></tr></thead><tbody>{matches.slice(current * 25, current * 25 + 25).map((item, index) => {
      const row = record(item);
      const list = category === 'tasks' ? row.required_params : row.tags;
      const details = category === 'relations' ? row.unary === true ? 'Unary' : row.unary === false ? 'Binary' : 'Not provided' : Array.isArray(list) ? list.filter((item): item is string => typeof item === 'string').slice(0, 50).map(item => item.slice(0, 256)).join(', ') : 'Not provided';
      return <tr key={index}><td>{text(row.name).slice(0, 1024)}</td><td>{details}</td><td>{text(row.summary).slice(0, 1024)}</td></tr>;
    })}</tbody></table>
    <button type="button" aria-label="Previous registry page" disabled={!current} onClick={() => setPage(current - 1)}>Previous</button>
    <span>Page {current + 1} / {Math.max(1, Math.ceil(matches.length / 25))}</span>
    <button type="button" aria-label="Next registry page" disabled={(current + 1) * 25 >= matches.length} onClick={() => setPage(current + 1)}>Next</button>
  </>;
}
export function MetadataBrowser() {
  const { api, session, status } = useRuntime();
  if (!session || status === 'expired' || api.session?.session_id !== session.session_id) return <section aria-label="Schema and registries"><button type="button" aria-expanded={false} disabled>Open schema and registries</button><p>Connect a session to browse metadata.</p></section>;
  return <SessionMetadataBrowser key={session.session_id} />;
}
function SessionMetadataBrowser() {
  const { api, session } = useRuntime();
  const [open, setOpen] = useState(false);
  const schema = useQuery({ queryKey: ['metadata-schema', session?.session_id], queryFn: () => api.get<unknown>('/editor/schema'), enabled: open && !!session, retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false });
  const catalogues = useQuery({ queryKey: ['metadata-catalogues', session?.session_id], queryFn: () => api.get<unknown>('/editor/catalogues'), enabled: open && !!session, retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false });
  return <section aria-label="Schema and registries">
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Close schema and registries' : 'Open schema and registries'}</button>
    {open && <>
      <h3>Schema</h3>
      {schema.isFetching && <p role="status">Loading schema…</p>}
      {schema.isError && <p role="alert">Schema could not be loaded. <button type="button" onClick={() => void schema.refetch()}>Retry schema</button></p>}
      {schema.isSuccess && <><p>Schema SHA-256: <code>{text(record(schema.data).schema_sha256).slice(0, 256)}</code></p><PropertyTree value={record(schema.data).schema} /><button type="button" disabled={schema.isFetching} onClick={() => void schema.refetch()}>Refresh schema</button></>}
      <h3>Registries</h3>
      {catalogues.isFetching && <p role="status">Loading registries…</p>}
      {catalogues.isError && <p role="alert">Registries could not be loaded. <button type="button" onClick={() => void catalogues.refetch()}>Retry registries</button></p>}
      {catalogues.isSuccess && <><RegistryTable value={catalogues.data} /><button type="button" disabled={catalogues.isFetching} onClick={() => void catalogues.refetch()}>Refresh registries</button></>}
    </>}
  </section>;
}
