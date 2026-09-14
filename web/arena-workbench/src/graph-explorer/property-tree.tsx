import { useState } from 'react';

const PAGE = 100;
const MAX_ROWS = 500;
const TEXT_SEGMENT = 1024; // At most 4 KiB of UTF-8, without building a whole-tree string.
interface Row { path: string[]; name: string; value: unknown; depth: number }
const pathKey = (path: string[]) => JSON.stringify(path);
const isContainer = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object';

/** Paginated disclosure tree; raw values never become HTML, URLs, or serialized whole trees. */
export function PropertyTree({ value }: { value: unknown }) {
  const [expanded, setExpanded] = useState(() => new Set(['[]']));
  const [pages, setPages] = useState(() => new Map<string, number>());
  const [segments, setSegments] = useState(() => new Map<string, number>());
  const [openNames, setOpenNames] = useState(() => new Set<string>());
  const rows: Row[] = [];
  let limited = false;
  function collect(item: unknown, path: string[], name: string, depth: number, ancestors: Set<object>) {
    if (rows.length >= MAX_ROWS) { limited = true; return; }
    rows.push({ path, name, value: item, depth });
    if (!isContainer(item) || !expanded.has(pathKey(path))) return;
    if (ancestors.has(item) || depth >= 32) { limited = true; return; }
    const nextAncestors = new Set(ancestors).add(item);
    const keys = Object.keys(item);
    const start = Math.min(pages.get(pathKey(path)) ?? 0, Math.max(0, Math.ceil(keys.length / PAGE) - 1)) * PAGE;
    for (const child of keys.slice(start, start + PAGE)) {
      collect(item[child], [...path, child], child, depth + 1, nextAncestors);
      if (rows.length >= MAX_ROWS) { limited = true; break; }
    }
  }
  collect(value, [], 'Properties', 0, new Set());
  function page(key: string, current: number, delta: number) {
    setPages(old => new Map(old).set(key, Math.max(0, current + delta)));
  }
  function textSegment(text: string, key: string, label: string) {
    let start = Math.min(segments.get(key) ?? 0, Math.max(0, text.length - 1));
    if (start > 0 && /[\uDC00-\uDFFF]/.test(text[start])) start--;
    let end = Math.min(text.length, start + TEXT_SEGMENT);
    if (end < text.length && /[\uD800-\uDBFF]/.test(text[end - 1])) end--;
    return <><pre>{text.slice(start, end)}</pre>{text.length > TEXT_SEGMENT && <span className="graph-property-pages">
      <button type="button" aria-label={`Previous text segment for ${label}`} disabled={!start} onClick={() => setSegments(old => new Map(old).set(key, Math.max(0, start - TEXT_SEGMENT)))}>Previous text</button>
      <span>Characters {start + 1}–{end} / {text.length}</span>
      <button type="button" aria-label={`Next text segment for ${label}`} disabled={end >= text.length} onClick={() => setSegments(old => new Map(old).set(key, end))}>Next text</button>
    </span>}</>;
  }
  return <div className="graph-properties">
    <button type="button" onClick={() => { setExpanded(new Set(['[]'])); setPages(new Map()); setSegments(new Map()); setOpenNames(new Set()); }}>
      Collapse all properties
    </button>
    {rows.map((row, index) => {
      const key = pathKey(row.path);
      const container = isContainer(row.value);
      const count = container ? Object.keys(row.value as object).length : 0;
      const currentPage = Math.min(pages.get(key) ?? 0, Math.max(0, Math.ceil(count / PAGE) - 1));
      const text = container ? '' : row.value === null ? 'null' : row.value === undefined ? 'Not provided' : String(row.value);
      const name = row.name.length > 160 ? `${row.name.slice(0, 157)}… (row ${index + 1})` : row.name;
      const valueType = row.value === null ? 'null' : typeof row.value;
      return <div key={key} data-property-row data-value-type={container ? undefined : valueType} className="graph-property-row" style={{ paddingLeft: `${Math.min(row.depth, 8) * 12}px` }}>
        {row.name.length > 160 && <>
          <button type="button" aria-expanded={openNames.has(key)} onClick={() => setOpenNames(old => { const next = new Set(old); if (next.has(key)) next.delete(key); else next.add(key); return next; })}>Inspect full property name (row {index + 1})</button>
          {openNames.has(key) && textSegment(row.name, `${key}:name`, `property name at row ${index + 1}`)}
        </>}
        {container ? <>
          <button type="button" aria-expanded={expanded.has(key)} aria-label={`${expanded.has(key) ? 'Collapse' : 'Expand'} ${name}`}
            onClick={() => setExpanded(old => { const next = new Set(old); if (next.has(key)) next.delete(key); else next.add(key); return next; })}>
            {expanded.has(key) ? '▾' : '▸'} {row.name.slice(0, 160)} · {Array.isArray(row.value) ? 'Array' : 'Object'} ({count})
          </button>
          {expanded.has(key) && count > PAGE && <span className="graph-property-pages">
            <button type="button" aria-label={`Previous properties page for ${name}`} disabled={currentPage === 0} onClick={() => page(key, currentPage, -1)}>Previous</button>
            <span>{currentPage + 1} / {Math.ceil(count / PAGE)}</span>
            <button type="button" aria-label={`Next properties page for ${name}`} disabled={(currentPage + 1) * PAGE >= count} onClick={() => page(key, currentPage, 1)}>Next</button>
          </span>}
        </> : <>
          {row.depth > 0 && <strong>{row.name.slice(0, 160)}</strong>}
          <small className="muted">Type: {valueType}</small>
          {textSegment(text, key, name)}
        </>}
      </div>;
    })}
    {limited && <p role="status">Property display limit reached. Collapse a branch or change its page to inspect more.</p>}
  </div>;
}
