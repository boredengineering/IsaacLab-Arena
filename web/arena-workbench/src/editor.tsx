import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRuntime } from './runtime';
import { ModelSettings, useModelSettings } from './model-settings';
import { CodeEditor } from './code-editor';
import { GraphView } from './graph-view';
import type {
  EditorDocument,
  EditorIndex,
  GeneratedResult,
  Revision,
  RenderOptions,

  Validation,
} from './editor-contracts';
import { EditorJobProgress, useEditorJob } from './editor-jobs';
import { AssetGrid, CameraSelect, defaultRenderOptions, SnapshotControls, SnapshotGallery, useSnapshots } from './snapshots';
import { snapshotHistorical, snapshotMatches } from './snapshot-model';
import { downloadRecoveredYaml, readDraft, storeDraft } from './draft-storage';
import type { RecoverableDraft } from './draft-storage';

export function RawTable({ title, rows }: { title: string; rows: Record<string, unknown>[] }) {
  return (
    <section className="raw-section">
      <h3>
        {title} <span className="muted">({rows.length})</span>
      </h3>
      {rows.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Kind / ID</th>
                <th>Full authored definition</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  <td>{String(row.kind ?? row.id ?? row.composition ?? i)}</td>
                  <td>
                    <pre>{JSON.stringify(row, null, 2)}</pre>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">None authored.</p>
      )}
    </section>
  );
}
/** Server-validated authoring surface; simulator work is always explicit. */
export function EditorView() {
  const { api, session } = useRuntime();
  const modelSettings = useModelSettings();
  const cache = useQueryClient();
  cache.setQueryDefaults(['editor-draft'], { gcTime: Infinity });
  const [restored] = useState(() =>
    cache.getQueryData<{
      documentId: string;
      loadedDocumentId?: string;
      document: EditorDocument | null;
      draft: string;
      prompt: string;
      validation: { text: string; result: Validation } | null;
      recovery: RecoverableDraft | null;
    }>(['editor-draft']),
  );
  const [recovery, setRecovery] = useState(() => restored ? restored.recovery : readDraft());
  const [storageError, setStorageError] = useState(false);
  const index = useQuery({
    queryKey: ['editor', session?.session_id],
    queryFn: () => api.get<EditorIndex>('/editor'),
    enabled: !!session,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const [documentId, setDocumentId] = useState(restored?.documentId ?? recovery?.documentId ?? '');
  const [loadedDocumentId, setLoadedDocumentId] = useState(
    restored?.loadedDocumentId ?? (restored?.document ? restored.documentId : ''),
  );
  const [document, setDocument] = useState<EditorDocument | null>(restored?.document ?? null);
  const [draft, setDraft] = useState(restored?.draft ?? '');
  const [validation, setValidation] = useState<{ text: string; result: Validation } | null>(
    restored?.validation ?? null,
  );
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(false);
  const [prompt, setPrompt] = useState(restored?.prompt ?? '');
  useEffect(() => {
    cache.setQueryData(['editor-draft'], { documentId, loadedDocumentId, document, draft, prompt, validation, recovery });
  }, [cache, documentId, loadedDocumentId, document, draft, prompt, validation, recovery]);
  useEffect(() => {
    if (recovery || loading || !document || loadedDocumentId !== documentId) return;
    setStorageError(!storeDraft(draft === document.yaml_text && !prompt ? null : {
      version: 1, documentId, viewId: document.document_id, sourceHash: document.source_hash, draft, prompt,
    }));
  }, [recovery, loading, document, loadedDocumentId, documentId, draft, prompt]);
  const request = useRef(0);
  const latest = useRef(draft);
  latest.current = draft;
  const generation = useEditorJob('generate');
  const generationAvailable = modelSettings.generationAvailable ?? index.data?.capabilities.generation;
  const current = validation?.text === draft ? validation.result : null;
  const valid = current?.valid === true;
  const canonicalHash = valid ? current.canonical_hash : null;
  const [previewMode, setPreviewMode] = useState('assets');
  const [cameraOptions, setCameraOptions] = useState<RenderOptions>(defaultRenderOptions);
  const options = { ...cameraOptions, asset_views: Object.fromEntries(Object.entries(cameraOptions.asset_views)
    .filter(([id]) => !valid || current.assets.some((asset) => asset.id === id))) };
  const snapshots = useSnapshots(canonicalHash, document?.document_id ?? '', options);
  const generated =
    generation.job?.status === 'succeeded' && typeof generation.job.result?.yaml_text === 'string'
      ? (generation.job.result as unknown as GeneratedResult)
      : null;
  const [appliedJob, setAppliedJob] = useState('');
  const save = useMutation({
    retry: false,
    mutationFn: async (payload: { yaml_text: string; document_id?: string; expected_source_hash?: string }) => {
      await api.activity();
      const revision = await api.mutate<Revision>('/editor/save', payload);
      return { revision, text: payload.yaml_text };
    },
  });
  function applyGenerated() {
    if (!generated) return;
    if (
      draft !== generation.retained?.payload.base_yaml &&
      !window.confirm(
        'Your draft changed after generation started. Replace it with the generated YAML?',
      )
    )
      return;
    setDraft(generated.yaml_text);
    setValidation({ text: generated.yaml_text, result: generated.validation });
    setAppliedJob(generation.job!.id);
  }
  useEffect(() => {
    if (index.data && !documentId) setDocumentId(index.data.default_document_id);
  }, [index.data, documentId]);
  useEffect(() => {
    if (!documentId || !session || (document && loadedDocumentId === documentId)) return;
    let active = true;
    setLoading(true);
    setError('');
    api
      .get<EditorDocument>(`/editor/documents/${encodeURIComponent(documentId)}`)
      .then((doc) => {
        if (active) {
          setDocument(doc);
          setLoadedDocumentId(documentId);
          setDraft(doc.yaml_text);
          setValidation({ text: doc.yaml_text, result: doc.validation });
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, documentId, session?.session_id]);
  async function validate(text = draft) {
    const sequence = ++request.current;
    setChecking(true);
    setError('');
    try {
      const result = await api.mutate<Validation>('/editor/validate', {
        yaml_text: text,
        ...(document ? { document_id: document.document_id } : {}),
      });
      if (sequence === request.current && latest.current === text) setValidation({ text, result });
    } catch (e) {
      if (sequence === request.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (sequence === request.current) setChecking(false);
    }
  }
  useEffect(() => {
    setChecking(false);
    if (!session || !draft || validation?.text === draft || loading || !index.data) return;
    const timer = setTimeout(() => void validate(draft), 650);
    return () => {
      clearTimeout(timer);
      request.current++;
    };
  }, [draft, documentId, session?.session_id, loading, index.data]);
  function chooseDocument(id: string) {
    if (
      document &&
      draft !== document.yaml_text &&
      !window.confirm('Discard this unsaved draft and load another document?')
    )
      return;
    request.current++;
    setDocumentId(id);
  }
  return (
    <main id="workspace" className="workspace editor-workspace">
      <div className="page-heading">
        <div>
          <span className="eyebrow">ENVIRONMENT AUTHORING</span>
          <h1>ArenaEnvGraphSpec live editor</h1>
          <p>Author a scene, inspect its relationships, then render it in Isaac Sim.</p>
        </div>
        <span className="tag">Source files stay untouched</span>
      </div>
      <div className="document-bar">
        <label>
          Document
          <select
            aria-label="Document"
            value={documentId}
            disabled={!index.data || loading}
            onChange={(e) => chooseDocument(e.target.value)}
          >
            <option value="" disabled>
              Select a document
            </option>
            {index.data?.documents.map((doc) => (
              <option key={doc.id} value={doc.id}>
                {doc.name}
              </option>
            ))}
          </select>
        </label>
        <span className="source-path">
          {document?.source ?? 'Connect to load an environment document'}
        </span>
        <span className="tag">
          {loading
            ? 'Loading…'
            : document && draft !== document.yaml_text
              ? 'Unsaved draft'
              : document
                ? 'Source loaded'
                : 'No document loaded'}
        </span>
      </div>
      {recovery && document && !loading && (
        <div className="notice warning" role="alert">
          <strong>Unsaved draft recovered from this tab</strong>
          <span>
            {recovery.viewId === document.document_id && recovery.sourceHash === document.source_hash
              ? 'Restore it explicitly, or keep the source currently shown. No job will be restarted.'
              : 'The source or included YAML changed. Download your draft before discarding it; automatic context substitution is blocked.'}
          </span>
          <div className="editor-actions">
            <button disabled={recovery.viewId !== document.document_id || recovery.sourceHash !== document.source_hash}
              onClick={() => {
                if (recovery.draft !== draft) setValidation(null);
                setDraft(recovery.draft); setPrompt(recovery.prompt); setRecovery(null);
              }}>Restore draft</button>
            <button onClick={() => downloadRecoveredYaml(recovery.draft)}>Download recovered YAML</button>
            <button onClick={() => { storeDraft(null); setRecovery(null); }}>Discard recovered draft</button>
          </div>
        </div>
      )}
      {storageError && (
        <div className="notice warning" role="alert">
          <span>Browser draft storage is unavailable or this draft exceeds its limits. The current draft is not backed up. Export your YAML before reloading.</span>
          <button onClick={() => downloadRecoveredYaml(draft, 'arena-draft.yaml')}>Download current YAML</button>
        </div>
      )}
      {index.error && (
        <div className="notice error" role="alert">
          <strong>Editor API unavailable</strong>
          <span>
            {index.error.message}. Your draft is not replaced; no generated content or images are
            inferred.
          </span>
          <button onClick={() => void index.refetch()}>Retry editor connection</button>
        </div>
      )}
      {index.data?.limitations.length ? (
        <details className="limitations">
          <summary>Adapter limitations</summary>
          <ul>
            {index.data.limitations.map((text, i) => (
              <li key={i}>{text}</li>
            ))}
          </ul>
        </details>
      ) : null}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      <div className="editor-grid">
        <div className="author-column">
          <section className="prompt-section">
            <div className="section-heading">
              <h2>Generate from prompt</h2>
              <span className="tag">Draft only · no Neo4j publication</span>
            </div>
            <ModelSettings settings={modelSettings} />
            <label htmlFor="scene-prompt">Describe the environment and task</label>
            <textarea
              id="scene-prompt"
              rows={3}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe the robot, objects, spatial relationships and task…"
            />
            <div className="section-heading">
              <p className="muted">
                {generationAvailable
                  ? 'Review generated YAML before applying it.'
                  : 'Generation unavailable — requires a configured backend adapter.'}
              </p>
              <button
                className="primary"
                disabled={
                  !session ||
                  (!generationAvailable && !(generation.retained && !generation.job)) ||
                  (!prompt.trim() && !(generation.retained && !generation.job)) ||
                  generation.busy ||
                  loading ||
                  (!!recovery && !(generation.retained && !generation.job))
                }
                onClick={() =>
                  generation.submit.mutate({
                    prompt,
                    base_yaml: draft,
                    ...(modelSettings.credentialRef ? { credential_ref: modelSettings.credentialRef } : {}),
                    ...(document ? { document_id: document.document_id } : {}),
                  })
                }
              >
                {generation.submit.isPending
                  ? 'Submitting…'
                  : generation.retained && !generation.job
                    ? 'Retry generation request'
                    : 'Generate spec'}
              </button>
            </div>
            <EditorJobProgress controller={generation} />
            {generated && appliedJob !== generation.job?.id && (
              <div className="generated-review">
                <h3>Generated YAML · review before applying</h3>
                <pre>{generated.yaml_text}</pre>
                {generated.warnings?.map((warning, i) => (
                  <p key={i}>{warning}</p>
                ))}
                <button onClick={applyGenerated}>Apply generated YAML</button>
                <p className="hint">
                  Not published to Neo4j. Applying replaces the editor draft only.
                </p>
              </div>
            )}
          </section>
          <section className="yaml-section">
            <div className="section-heading">
              <h2>YAML editor</h2>
              <span className={`validation-status ${valid ? 'valid' : ''}`} role="status">
                {checking
                  ? 'Validating…'
                  : current
                    ? valid
                      ? 'Schema valid'
                      : 'Schema errors'
                    : draft
                      ? 'Draft changed · validation pending'
                      : 'No document'}
              </span>
            </div>
            <CodeEditor label="YAML editor" value={draft} onChange={setDraft} />
            <div className="editor-actions">
              <button
                disabled={!session || !index.data || !draft || checking}
                onClick={() => void validate()}
              >
                Validate schema
              </button>
              <button
                disabled={!session || !valid || save.isPending || loading || !!recovery}
                onClick={() => save.mutate({ yaml_text: draft, ...(document
                  ? { document_id: document.document_id, expected_source_hash: document.source_hash } : {}) })}
              >
                {save.isPending ? 'Saving…' : 'Save revision'}
              </button>
            </div>
            {save.error && (
              <p className="notice error" role="alert">
                {save.error.message}
              </p>
            )}
            {save.data && (
              <div className="saved-revision">
                <p role="status">
                  Revision saved · {save.data.revision.revision_id}
                  {save.data.text !== draft ? ' · older than current draft' : ''}
                </p>
                {/^\/api\/editor\/revisions\/[^/]+\/download$/.test(
                  save.data.revision.download_url,
                ) && (
                  <a href={save.data.revision.download_url} download>
                    Export flattened YAML
                  </a>
                )}
              </div>
            )}
            <p className="hint">
              Validation uses the server’s ArenaEnvGraphSpec model. Saving creates an immutable
              revision, never overwrites source YAML.
            </p>
            {current && (
              <div className="schema-diagnostics">
                <p>{current.summary}</p>
                {current.errors.map((text, i) => (
                  <pre className="error-text" role="alert" key={i}>
                    {text}
                  </pre>
                ))}
                {current.warnings.map((text, i) => (
                  <p className="warning-text" key={i}>
                    {text}
                  </p>
                ))}
                <details>
                  <summary>Schema hashes</summary>
                  <pre>
                    {JSON.stringify(
                      { source_hash: current.source_hash, canonical_hash: current.canonical_hash },
                      null,
                      2,
                    )}
                  </pre>
                </details>
              </div>
            )}
          </section>
        </div>
        <div className="visual-column">
          <section>
            <div className="section-heading">
              <div>
                <h2>Visualization</h2>
                <p className="muted">
                  {valid ? current.summary : 'Validate YAML to synchronize the authored scene.'}
                </p>
              </div>
              <span className="tag">Authored · not Neo4j</span>
            </div>
            <div className="section-heading asset-heading">
              <h3>Assets</h3>
              <SnapshotControls
                key={`${session?.session_id}:${document?.document_id}`}
                snapshots={snapshots}
                draft={draft}
                documentId={document?.document_id ?? ''}
                enabled={!!session && valid && !loading && !recovery && index.data?.capabilities.snapshots === true}
              />
            </div>
            <div className="preview-options">
              <label>Preview mode<select aria-label="Preview mode" value={previewMode} onChange={(e) => setPreviewMode(e.target.value)}>
                <option value="assets">Assets</option><option value="scene">Scene</option>
              </select></label>
              <CameraSelect label="Scene camera" value={options.view} onChange={(view) => setCameraOptions((old) => ({ ...old, view }))} />
              <label>Image resolution<select aria-label="Image resolution" value={options.resolution} onChange={(e) => setCameraOptions((old) => ({ ...old, resolution: Number(e.target.value) as 512 | 1024 }))}>
                <option value="512">512 × 512</option><option value="1024">1024 × 1024</option>
              </select></label>
              <button disabled={!canonicalHash || snapshots.lookup.isFetching} onClick={() => void snapshots.lookup.refetch()}>Refresh saved previews</button>
            </div>
            <p className="hint preview-status">
              {snapshotHistorical(snapshots.history[0])
                ? 'Historical saved pixels shown; asset freshness is unverified. Render explicitly to update.'
                : snapshotMatches(snapshots.history[0], canonicalHash)
                  ? 'Saved previews match the validated scene.'
                  : snapshots.history.length
                    ? 'Older previews shown. Render snapshots to update this scene.'
                    : 'No saved previews for this scene. Render snapshots to create asset and scene images.'}
              {' '}GPU rendering is off by default. Automatic previews require explicit consent and a bounded job budget.
            </p>
            {snapshots.lookup.isFetching && <p role="status">Looking up saved previews…</p>}
            {snapshots.lookup.isError && <p className="notice warning" role="alert">Preview catalogue unavailable. {snapshots.lookup.error.message} No journal fallback is trusted.</p>}
            {snapshots.lookup.data?.status === 'miss' && <p>No saved previews for these camera options.</p>}
            <EditorJobProgress controller={snapshots.controller} />
            {previewMode === 'assets' ? <AssetGrid
              assets={valid ? current.assets : []}
              receipt={snapshots.history[0]}
              stale={!snapshotMatches(snapshots.history[0], canonicalHash)}
              options={options}
              onCamera={(id, view) => setCameraOptions((old) => {
                const asset_views = { ...old.asset_views };
                if (view) asset_views[id] = view; else delete asset_views[id];
                return { ...old, asset_views };
              })}
            /> : <SnapshotGallery snapshots={snapshots} canonicalHash={canonicalHash} />}
            <div className="section-heading graph-heading">
              <h3>Authored spatial graph</h3>
              <span className="muted">Synchronized with validated YAML</span>
            </div>
            {valid ? (
              <GraphView graph={current.graph} label="Authored spatial graph" />
            ) : (
              <div className="empty-state">
                {draft
                  ? 'Graph withheld until this draft validates. No stale graph is presented as current.'
                  : 'Load or paste an environment to explore its authored graph.'}
              </div>
            )}
            {valid && (
              <>
                <RawTable
                  title="Unary constraints"
                  rows={current.relations.filter((row) => row.reference == null)}
                />
                <details className="relation-details">
                  <summary>All relations and explicit reifiers</summary>
                  <RawTable title="Relations" rows={current.relations} />
                  <RawTable title="Explicit reifiers" rows={current.reified_relations} />
                </details>
                <RawTable title="Tasks" rows={current.tasks} />
              </>
            )}
          </section>

        </div>
      </div>
    </main>
  );
}
