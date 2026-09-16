import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError } from './api';
import { useRuntime } from './runtime';
import { decodeEditorSaveReceipt, editorSaveRequestHash, type EditorRevision, type EditorSaveReceipt, type EditorSaveRequest } from './editor-revision-contracts';
export interface EditorRevisionSaveProps {
  enabled: boolean;
  // Activity admission for receipt reads/Open; writes additionally need enabled.
  // Omitted callers retain the legacy combined gate.
  readEnabled?: boolean;
  draft: string;
  documentId?: string;
  expectedSourceHash?: string;
  bindingKey: string;
  onSaved?: (revision: EditorRevision) => void;
  onOpen?: (descriptor: EditorRevision['open_source']) => void;
}
const KEY = 'arena:editor-save:v1';
const LIMIT = 256 * 1024;
interface Pending { schema_version: 1; binding: string; request: EditorSaveRequest; request_sha256: string; accepted?: EditorSaveReceipt }
const size = (text: string) => new TextEncoder().encode(text).length;
function fitsAcceptance(record: Pending): boolean {
  const request = record.request, id = 'f'.repeat(32), digest = 'f'.repeat(64);
  const maximum: EditorSaveReceipt = { schema_version: 1, idempotency_key: request.idempotency_key,
    request_sha256: record.request_sha256, state: 'committed', revision: {
      revision_id: id, yaml_text: request.yaml_text, source_hash: digest, canonical_hash: digest,
      download_url: `/api/editor/revisions/${id}/download`, open_source: { kind: 'editor_revision', id: `editor-revision:${id}` },
    } };
  return size(JSON.stringify({ ...record, accepted: maximum })) <= LIMIT;
}
function readPending(provided?: string): { raw: string | null; pending?: Pending; error?: string } {
  try {
    const raw = provided === undefined ? sessionStorage.getItem(KEY) : provided;
    if (raw === null) return { raw };
    if (size(raw) > LIMIT) throw new Error();
    const p = JSON.parse(raw) as Pending, r = p?.request;
    if (p.schema_version !== 1 || typeof p.binding !== 'string' || !p.binding || p.binding.length > 2048
      || !/^[a-f0-9]{64}$/.test(p.request_sha256) || !r || typeof r.yaml_text !== 'string'
      || typeof r.idempotency_key !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(r.idempotency_key)
      || (r.document_id !== undefined && (typeof r.document_id !== 'string' || !r.document_id || r.document_id.length > 2048))
      || (r.expected_source_hash !== undefined && !/^[a-f0-9]{64}$/.test(r.expected_source_hash))
      || ('accepted' in p && (!p.accepted || typeof p.accepted !== 'object' || Array.isArray(p.accepted)))
      || Object.keys(p).some(k => !['schema_version', 'binding', 'request', 'request_sha256', 'accepted'].includes(k))
      || Object.keys(r).some(k => !['yaml_text', 'idempotency_key', 'document_id', 'expected_source_hash'].includes(k))) throw new Error();
    return { raw, pending: p };
  } catch { return { raw: null, error: 'Conflict — storage unreadable, corrupt or oversized; preserve evidence and download raw YAML.' }; }
}
export function EditorRevisionSave(props: EditorRevisionSaveProps) {
  const { api, health } = useRuntime();
  const supported = (health?.capabilities as { durable_editor_save?: boolean } | undefined)?.durable_editor_save === true;
  // Render-time authority, not a fresh session snapshot taken by a retired click handler.
  const generation = api.sessionGeneration;
  const readEnabled = props.readEnabled ?? props.enabled;
  const owner = useMemo(() => ({}), [api, generation, props.bindingKey, props.enabled, readEnabled, supported]);
  const currentOwner = useRef(owner); currentOwner.current = owner;
  const onSaved = useRef(props.onSaved); onSaved.current = props.onSaved;
  const onOpen = useRef(props.onOpen); onOpen.current = props.onOpen;
  const alive = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const [initial] = useState(readPending);
  const [pending, setPending] = useState(initial.pending);
  const baseline = useRef(initial.raw);
  const [status, setStatus] = useState(initial.error ?? (pending ? 'Unknown — retained save; check status or retry exact save' : 'Ready'));
  const [blocked, setBlocked] = useState(!!initial.error);
  const [saved, setSaved] = useState<{ revision: EditorRevision; request: EditorSaveRequest; owner: object }>();
  const revision = saved?.owner === owner ? saved.revision : undefined;
  const alreadySaved = saved?.owner === owner && saved.request.yaml_text === props.draft
    && saved.request.document_id === props.documentId && saved.request.expected_source_hash === props.expectedSourceHash;
  const visibleStatus = status === 'Saved' ? !revision ? 'Retired saved result — reopen in the current session'
    : alreadySaved ? status : 'Saved frozen revision — current draft has unsaved changes' : status;
  const busy = useRef(false);
  const [working, setWorking] = useState(false);
  const matches = !pending || (pending.binding === props.bindingKey && pending.request.yaml_text === props.draft
    && pending.request.document_id === props.documentId && pending.request.expected_source_hash === props.expectedSourceHash);
  const current = () => alive.current && currentOwner.current === owner && api.sessionGeneration === generation && !!api.session;
  const storageLost = useRef(false);
  const memoryAccepted = useRef<EditorSaveReceipt | undefined>(undefined);
  const attemptedAcceptance = useRef<string | undefined>(undefined);
  const retentionFits = !pending || fitsAcceptance(pending);
  async function run(post: boolean) {
    if (!current()) { setStatus('Retired controls — reconnect and review explicitly'); return; }
    if (busy.current || blocked || !supported || !readEnabled || (post ? !props.enabled : !pending)
      || (post && (!matches || !retentionFits || storageLost.current || pending?.accepted || alreadySaved))) return;
    busy.current = true; setWorking(true);
    let record = pending;
    let sent = !!pending;
    const conflict = () => new Error('Conflict');
    const assertStorage = (readOnly = false) => {
      let raw: string | null;
      try { raw = sessionStorage.getItem(KEY); }
      catch { if (readOnly && memoryAccepted.current) { storageLost.current = true; return; } throw new Error('Storage'); }
      if (raw !== baseline.current) {
        // A successful ACK write can have an unreadable verification read. Only
        // its exact checked bytes, never a sibling's replacement, qualify.
        if (readOnly && memoryAccepted.current && raw === attemptedAcceptance.current) { baseline.current = raw; return; }
        if (raw === null && readOnly && memoryAccepted.current) { storageLost.current = true; return; }
        throw conflict();
      }
    };
    const retain = (value: Pending) => {
      assertStorage();
      const text = JSON.stringify(value);
      if (readPending(text).error) throw new Error('Storage');
      if (value.accepted && memoryAccepted.current === value.accepted) attemptedAcceptance.current = text;
      sessionStorage.setItem(KEY, text);
      if (sessionStorage.getItem(KEY) !== text) throw new Error('Storage');
      baseline.current = text;
    };
    try {
      assertStorage(!post);
      if (!record) {
        if (baseline.current !== null) throw conflict();
        memoryAccepted.current = undefined;
        attemptedAcceptance.current = undefined;
        // All editable values are captured synchronously, before hashing or transport awaits.
        const request: EditorSaveRequest = { idempotency_key: crypto.randomUUID(), yaml_text: props.draft,
          ...(props.documentId !== undefined ? { document_id: props.documentId } : {}),
          ...(props.expectedSourceHash !== undefined ? { expected_source_hash: props.expectedSourceHash } : {}) };
        record = { schema_version: 1, binding: props.bindingKey, request, request_sha256: await editorSaveRequestHash(request) };
        if (!current()) return;
        // Bound the entire eventual ACK record, not just pre-ACK YAML. Fixed
        // wire identifiers/hashes have exact maxima; escaping counts as UTF-8 JSON.
        if (!fitsAcceptance(record)) throw new Error('Storage');
        retain(record); setPending(record);
      }
      if (await editorSaveRequestHash(record.request) !== record.request_sha256) throw conflict();
      if (record.accepted) {
        await decodeEditorSaveReceipt(record.accepted, record.request);
        if (!current()) return;
      }
      if (!current()) return;
      if (post) {
        assertStorage();
        setStatus(pending ? 'Retrying exact save' : 'Pending'); sent = true;
        const wire = await api.mutate('/editor/save', record.request);
        if (!current()) return;
        const accepted = await decodeEditorSaveReceipt(wire, record.request);
        if (!current()) return;
        // Remember checked acceptance BEFORE storage; never convert quota loss into a new POST.
        memoryAccepted.current = accepted; record = { ...record, accepted }; setPending(record);
        try { assertStorage(true); if (!storageLost.current) retain(record); }
        catch (error) { if (error instanceof Error && error.message === 'Conflict') throw error; storageLost.current = true; }
      }
      assertStorage(true);
      setStatus(record.accepted ? 'Known accepted — verifying readback' : 'Readback — checking save status');
      const wire = await api.get(`/editor/save-requests/${encodeURIComponent(record.request.idempotency_key)}`);
      if (!current()) return;
      const checked = await decodeEditorSaveReceipt(wire, record.request);
      if (!current()) return;
      if (record.accepted && JSON.stringify(checked) !== JSON.stringify(record.accepted)) throw conflict();
      // GET-only recovery establishes acceptance too, before any fallible cleanup.
      // Preserve the exact pre-ACK baseline for sibling ownership checks.
      memoryAccepted.current = checked; record = { ...record, accepted: checked }; setPending(record);
      assertStorage(true);
      if (storageLost.current) { setStatus('Known accepted — verified readback; storage lost, GET-only. Keep this tab open.'); return; }
      try {
        sessionStorage.removeItem(KEY);
        if (sessionStorage.getItem(KEY) !== null) throw conflict();
      } catch (error) {
        if (!(error instanceof Error && error.message === 'Conflict')) storageLost.current = true;
        throw error;
      }
      baseline.current = null; setPending(undefined);
      setSaved({ revision: checked.revision, request: record.request, owner }); setStatus('Saved');
      if (current()) onSaved.current?.(checked.revision);
    } catch (error) {
      if (!current()) return;
      if ((error instanceof ApiError && [409, 403, 422].includes(error.status))
        || (error instanceof Error && ['Conflict', 'Invalid editor save receipt', 'API returned an invalid response'].includes(error.message))) {
        setBlocked(true); setStatus('Conflict — invalid or replaced evidence; retained request requires review');
      } else if (storageLost.current && memoryAccepted.current) {
        setStatus('Known accepted — storage lost; readback unavailable, GET-only. Keep this tab open.');
      } else if (!sent || (error instanceof Error && error.message === 'Storage')) {
        setBlocked(true); setStatus('Storage unavailable — download raw YAML; no new save allowed');
      } else setStatus(record?.accepted ? 'Known accepted — readback unavailable' : 'Unknown — check status or retry exact save');
    } finally {
      busy.current = false;
      // Releasing this operation's UI lock is independent of callback authority.
      if (alive.current) setWorking(false);
    }
  }
  const readAllowed = readEnabled && supported && !!api.session && !blocked;
  const allowed = props.enabled && readAllowed;
  return <section aria-label="Durable editor save"><p role="status">{!supported ? 'Durable save unsupported by this API' : visibleStatus}</p>
    {pending && !matches && <p>Draft or binding changed. Only readback of the frozen request is allowed.</p>}
    {!retentionFits && <p>Retained request exceeds full receipt storage capacity. GET-only recovery; no replay.</p>}
    <button type="button" disabled={!allowed || !!pending || working || alreadySaved} onClick={() => void run(true)}>Save durable revision</button>
    {pending && <><button type="button" disabled={!readAllowed || working} onClick={() => void run(false)}>Check save status</button>
      <button type="button" disabled={!allowed || working || !matches || !retentionFits || !!pending.accepted || storageLost.current} onClick={() => void run(true)}>Retry exact save</button></>}
    {revision && <button type="button" disabled={!readAllowed} onClick={() => { if (current() && readAllowed) onOpen.current?.(revision.open_source); }}>Open saved revision</button>}
  </section>;
}
