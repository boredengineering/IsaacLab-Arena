import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import { AuthoredInspector, type AuthoredInspectorProps } from './authored-inspector';
import './editor-v7.css';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRuntime } from './runtime';
import type { ApiClient } from './api';
import { ModelSettings, useModelSettings } from './model-settings';
import { CodeEditor } from './code-editor';
import { GraphHost, type GraphRolloutProps } from './graph-host';
import { GenerationEvidence } from './generation-evidence';
import { MetadataBrowser } from './metadata-browser';
import { ResearchVersions } from './research-versions';
import { sameResearchIdentity, type ManualInput } from './research-source';
import { EnvironmentLibrary } from './environment-library';
import { LIBRARY_RECENT_LIMIT, normalizeLibrarySources, referenceKey, type SourceSummary } from './environment-library-contract';
import { EditorRevisionSave } from './editor-revision-save';
import { editorSourceHash, type EditorRevision } from './editor-revision-contracts';
import type {
  EditorDocument,
  EditorIndex,
  GeneratedResult,
  Revision,
  RenderOptions,

  Validation,
} from './editor-contracts';
import { EditorJobProgress, useEditorJob } from './editor-jobs';
import { BuildControls } from './build-environment';
import { EvaluationControls } from './evaluate-policy';
import { AssetGrid, CameraSelect, defaultRenderOptions, SnapshotControls, SnapshotGallery, useSnapshots } from './snapshots';
import { snapshotHistorical, snapshotMatches } from './snapshot-model';
import { downloadRecoveredYaml } from './draft-storage';
import { DraftController, NEW_DOCUMENT, type OwnedValidation } from './draft-controller';
// Stable across controller remounts, without retaining a client or its credentials in the draft cache.
const clientOwners = new WeakMap<ApiClient, string>();
function validationOwner(api: ApiClient, sessionId: string | undefined, sessionGeneration: number, documentId: string, document: EditorDocument | null) {
  let clientOwner = clientOwners.get(api);
  if (!clientOwner) { clientOwner = crypto.randomUUID(); clientOwners.set(api, clientOwner); }
  return JSON.stringify([clientOwner, sessionId, sessionGeneration, documentId, document?.document_id, document?.source_hash]);
}

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
export interface EditorViewProps extends GraphRolloutProps {
  layout?: 'legacy' | 'v7';
  active?: boolean;
  libraryActive?: boolean;
  onLibraryOpened?: () => void;
  renderInspector?: (props: AuthoredInspectorProps) => ReactNode;
}
/** One persistent authoring controller; layout changes only its presentation. */
export function EditorView({ graphRenderer = 'legacy', onGraphRendererChange = () => {}, layout = 'legacy', active = true, libraryActive = false, onLibraryOpened, renderInspector }: EditorViewProps = {}) {
  const v7 = layout === 'v7';
  const [generationOpen, setGenerationOpen] = useState(true);
  const [specificationOpen, setSpecificationOpen] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [focusRequest, setFocusRequest] = useState(0);
  const specification = useRef<HTMLElement>(null);
  useEffect(() => {
    if (focusRequest) specification.current?.querySelector<HTMLElement>('[role="textbox"]')?.focus();
  }, [focusRequest]);
  const { api, session, health } = useRuntime();
  const durableSave = (health?.capabilities as { durable_editor_save?: boolean } | undefined)?.durable_editor_save === true;
  const sessionGeneration = api.sessionGeneration;
  // Promote externally mutable ownership into React state. A no-op state render
  // must not consume changed effect dependencies without committing their cleanup/restart.
  const [sessionOwner, setSessionOwner] = useState(() => ({ api, generation: sessionGeneration }));
  if (sessionOwner.api !== api || sessionOwner.generation !== sessionGeneration) {
    setSessionOwner({ api, generation: sessionGeneration });
  }
  const latestApi = useRef(api);
  latestApi.current = api;
  function ownsSession() {
    return latestApi.current === api && !!session && api.sessionGeneration === sessionGeneration && api.session?.session_id === session.session_id;
  }
  const metadataOwner = validationOwner(api, session?.session_id, sessionGeneration, '', null);
  const modelSettings = useModelSettings(active);
  const cache = useQueryClient();
  cache.setQueryDefaults(['editor-draft'], { gcTime: Infinity });
  const [draftController] = useState(() => cache.getQueryData<DraftController>(['editor-draft']) ?? new DraftController());
  const {documentId, loadedDocumentId, document, draft, prompt, validation, recovery, storageStatus, reconciliation, loadRequest} = useSyncExternalStore(draftController.subscribe, draftController.getSnapshot);
  const storageError = storageStatus !== 'ready';
  const draftHandler = draftController.handler();
  useLayoutEffect(() => {
    cache.setQueryData(['editor-draft'], draftController);
    return draftController.activate();
  }, [cache, draftController]);
  const setValidation = (value: OwnedValidation | null) => draftController.setValidation(value, draftHandler);
  const ownsInput = () => draftController.live(draftHandler) && latestApi.current === api && api.sessionGeneration === sessionGeneration
    && active && renderedOpenAuthority === openAuthority.current;
  const indexQuery = useQuery({
    queryKey: ['editor', metadataOwner],
    queryFn: async () => {
      if (!ownsSession()) throw new Error('Editor metadata session changed.');
      try {
        const result = await api.get<EditorIndex>('/editor');
        if (!ownsSession()) throw new Error('Editor metadata session changed.');
        // Reject the entire envelope before rendering/normalizing. Never slice
        // raw rows: a duplicate outside that slice must quarantine its first row.
        if (!Array.isArray(result.documents) || result.documents.length > 2048
          || new TextEncoder().encode(JSON.stringify(result)).length > 2 * 1024 * 1024) throw new Error('Editor catalogue is malformed or exceeds safe bounds.');
        return result;
      } catch (error) {
        if (!ownsSession()) throw new Error('Editor metadata session changed.');
        throw error;
      }
    },
    enabled: (active || libraryActive) && !!session,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const index = { ...indexQuery, data: ownsSession() ? indexQuery.data : undefined };
  const libraryStatus = !ownsSession() || index.isError ? 'unavailable' : index.isFetching || !index.data ? 'loading' : 'ready';
  const catalogue = normalizeLibrarySources(index.data?.documents ?? []);
  // Mount-local, bounded verified discovery. Preferences never populate this inventory.
  const [researchInventory, setResearchInventory] = useState<{owner: string; sources: SourceSummary[]}>({owner: metadataOwner, sources: []});
  function librarySources(data: EditorIndex | undefined) {
    const rows = data?.documents as SourceSummary[] ?? [];
    const researchAllowed = data?.capabilities.research_version_open === true;
    // Even malformed/duplicate current rows take precedence over memory; never repair a conflict.
    return [...rows.filter(row => row?.kind !== 'research_version' || researchAllowed),
      ...(researchAllowed && researchInventory.owner === metadataOwner ? researchInventory.sources.filter(source => !rows.some(row => row?.id === source.id)) : [])];
  }
  const libraryRows = librarySources(index.data);
  const libraryCatalogue = normalizeLibrarySources(libraryRows);
  const latestCatalogue = useRef({ catalogue: libraryCatalogue, libraryStatus });
  latestCatalogue.current = { catalogue: libraryCatalogue, libraryStatus };
  const catalogueEpoch = useRef(0);
  const renderedCatalogueEpoch = catalogueEpoch.current;
  const pendingIndexOpen = useRef<number | null>(null);
  const [opened, setOpened] = useState<{ source: SourceSummary; sequence: number; owner: string }>();
  const openedSequence = useRef(0);
  const openEpoch = useRef(0);
  const openAuthority = useRef({ metadataOwner, active, libraryActive });
  if (openAuthority.current.metadataOwner !== metadataOwner || openAuthority.current.active !== active || openAuthority.current.libraryActive !== libraryActive) {
    openEpoch.current++;
    openAuthority.current = { metadataOwner, active, libraryActive };
  }
  const renderedOpenAuthority = openAuthority.current;
  const renderedOpenEpoch = openEpoch.current;
  const savedRevision = useRef<EditorRevision | undefined>(undefined);
  const [numberedSource, setNumberedSource] = useState<{source: ManualInput; owner: string; document: string; authority: typeof renderedOpenAuthority}>();

  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  // Query notifications are synchronous: even refresh or data A→B→A before
  // React commits must retire catalogue AND original research Open permission.
  // Independently verified editor receipts retain separate GET-only authority.
  useLayoutEffect(() => cache.getQueryCache().subscribe(event => {
    if ((event.type !== 'updated' && event.type !== 'removed')
      || event.query.queryKey[0] !== 'editor' || event.query.queryKey[1] !== metadataOwner) return;
    catalogueEpoch.current++;
    if (pendingIndexOpen.current === openEpoch.current) {
      draftController.retireLoad();
      openEpoch.current++;
      pendingIndexOpen.current = null;
      setLoading(false);
    }
  }), [cache, metadataOwner]);
  useEffect(() => { setLoading(false); }, [renderedOpenAuthority]);
  const [checking, setChecking] = useState(false);

  const [generationMode, setGenerationMode] = useState<'new' | 'refine'>('new');
  const [retrievalPolicy, setRetrievalPolicy] = useState<'allow_fallback' | 'require_service'>('allow_fallback');
  const modesAvailable = index.data?.capabilities.generation_modes === true;

  const request = useRef(0);
  const latest = useRef(draft);
  latest.current = draft;
  const generation = useEditorJob('generate');
  const retryGeneration = !!generation.retained && !generation.job;
  // Accepted inputs, not a tab's retry payload, define the durable operation.
  const generationInputs = generation.job ? generation.job.inputs : generation.retained?.payload;
  const frozenMode = generationInputs?.operation;
  const selectedMode = (generation.busy || retryGeneration) && (frozenMode === 'new' || frozenMode === 'refine')
    ? frozenMode : generationMode;
  const frozenPolicy = generationInputs?.retrieval_policy;
  const selectedPolicy = (generation.busy || retryGeneration) && (frozenPolicy === 'allow_fallback' || frozenPolicy === 'require_service')
    ? frozenPolicy : retrievalPolicy;
  const generationAvailable = modelSettings.generationAvailable ?? index.data?.capabilities.generation;
  const owner = validationOwner(api, session?.session_id, sessionGeneration, documentId, document);
  const latestOwner = useRef(owner);
  latestOwner.current = owner;
  const current = ownsSession() && loadedDocumentId === documentId && validation?.owner === owner && validation.text === draft
    ? validation.result : null;
  // Monotonic bindings prevent A→B→A from reviving an inspector callback or
  // validation response. Presentation toggles deliberately do not retire ownership.
  const binding = useRef({ owner, draft, validation, active, sessionGeneration: api.sessionGeneration, epoch: 0 });
  if (binding.current.owner !== owner || binding.current.draft !== draft || binding.current.validation !== validation
    || binding.current.active !== active || binding.current.sessionGeneration !== api.sessionGeneration) {
    binding.current = { owner, draft, validation, active, sessionGeneration: api.sessionGeneration, epoch: binding.current.epoch + 1 };
  }
  const bindingEpoch = binding.current.epoch;
  const bindingKey = `${owner}:${bindingEpoch}`;
  function focusSpecification() {
    if (!ownsSession() || !active || !binding.current.active || binding.current.epoch !== bindingEpoch) return;
    setExpanded(false); setSpecificationOpen(true); setFocusRequest((value) => value + 1);
  }
  const valid = current?.valid === true;
  const canonicalHash = valid ? current.canonical_hash : null;
  const [previewMode, setPreviewMode] = useState('assets');
  const [cameraOptions, setCameraOptions] = useState<RenderOptions>(defaultRenderOptions);
  const options = { ...cameraOptions, asset_views: Object.fromEntries(Object.entries(cameraOptions.asset_views)
    .filter(([id]) => !valid || current.assets.some((asset) => asset.id === id))) };
  const editLifetime = useRef(true);
  const editEpoch = useRef(0);
  const [, publishEditEpoch] = useState(0);
  function retirePositionEdit() { editEpoch.current++; openEpoch.current++; if (loading) setLoading(false); publishEditEpoch(editEpoch.current); }
  useLayoutEffect(() => { editLifetime.current = true; return () => { editLifetime.current = false; editEpoch.current++; }; }, []);
  const editInputs = [bindingKey, cameraOptions, checking, error, loading, v7];
  const observedEditInputs = useRef(editInputs);
  if (editInputs.some((value, i) => value !== observedEditInputs.current[i])) {
    observedEditInputs.current = editInputs; editEpoch.current++;
  }
  const renderedEditEpoch = editEpoch.current;
  // Interactive authoring uses the rendered navigation/runtime owner as well
  // as the controller token. Retained content cannot lend a retired callback
  // the replacement UI's authority, even when the public session ID repeats.
  function ownsAuthoringCommand() {
    return editLifetime.current && active && ownsSession()
      && renderedOpenAuthority === openAuthority.current && draftController.eligible(draftHandler);
  }
  function ownsPositionEdit() {
    return editLifetime.current && editEpoch.current === renderedEditEpoch && ownsSession() &&
      active && v7 && binding.current.active && binding.current.epoch === bindingEpoch &&
      !checking && !error && !loading && loadedDocumentId === documentId && current?.valid === true;
  }
  function applyReviewedPosition(candidate: string) {
    if (!ownsPositionEdit() || !document || candidate === draft) return false;
    const operation = draftController.begin(draftHandler);
    if (!operation || !draftController.accept(documentId, document, candidate, null, operation)) return false;
    editEpoch.current++; request.current++;
    latest.current = candidate;
    setError('');
    // The normal owned draft-validation effect performs a NEW request. Candidate
    // findings never become current validation, even when canonical hashes agree.
    return true;
  }
  const inspectorProps: AuthoredInspectorProps = {
    validation: active ? current : null,
    bindingKey, onFocusSpecification: focusSpecification,
    editing: v7 ? { api, draft, documentId: document?.document_id ?? '', sourceHash: document?.source_hash ?? '',
      bindingKey, optionsKey: String(renderedEditEpoch), active, validationReady: !checking && !error && !loading,
      isCurrent: ownsPositionEdit, onApply: applyReviewedPosition } : undefined,
  };
  // Share F2's synchronous source/options epoch; snapshot dispatch is not an edit
  // and remains available in both layouts. Accepted jobs retain independent ownership.
  const ownsSnapshotControls = () => editLifetime.current && editEpoch.current === renderedEditEpoch
    && ownsSession() && active && binding.current.active && binding.current.epoch === bindingEpoch;
  const snapshots = useSnapshots(canonicalHash, document?.document_id ?? '', options, active, ownsSnapshotControls);
  const candidateValidation = generation.job?.result?.validation;
  const cancelledCandidate = generation.job?.status === 'cancelled' &&
    candidateValidation !== null && typeof candidateValidation === 'object' &&
    'valid' in candidateValidation && candidateValidation.valid === true;
  const generated =
    (generation.job?.status === 'succeeded' || cancelledCandidate) &&
      typeof generation.job?.result?.yaml_text === 'string' && generation.job.result.yaml_text.trim()
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
    if (!generated || !ownsAuthoringCommand()) return;
    const operation = draftController.begin(draftHandler);
    if (!operation) return;
    const inputs = generationInputs;
    const isNew = inputs?.operation === 'new';
    const hasSourceIdentity = !!inputs && ('document_id' in inputs || 'input_hash' in inputs);
    // Missing legacy provenance can only be applied detached, never reconstructed from retry storage.
    // A selected source may still be loading; never bind an old candidate to its includes.
    const sourceChanged = !hasSourceIdentity || loadedDocumentId !== documentId ||
      (inputs?.document_id ?? null) !== (document?.document_id ?? null) ||
      (typeof inputs?.input_hash === 'string' && inputs.input_hash !== current?.source_hash);
    if (
      (isNew || (sourceChanged && hasSourceIdentity) || draft !== (inputs?.base_yaml ?? generated.yaml_text)) &&
      !window.confirm(
        isNew ? 'Replace the current draft with this new environment? The previous document context will be detached.'
          : sourceChanged ? 'The source document or frozen inputs changed after generation started. Apply the generated YAML as a detached draft without the current source includes?'
            : 'Your draft changed after generation started. Replace it with the generated YAML?',
      )
    )
      return;
    if (!ownsAuthoringCommand() || !draftController.check(operation)) return;
    if (!draftController.accept(isNew || sourceChanged ? NEW_DOCUMENT : documentId, isNew || sourceChanged ? null : document, generated.yaml_text, null, operation)) return;
    retirePositionEdit();
    if (isNew || sourceChanged) {
      setNumberedSource(undefined);
      request.current++;
      setLoading(false);
    }

    // Durable job validation has no current session/source ownership. Validate the applied draft anew.
    setValidation(null);
    setAppliedJob(generation.job!.id);
  }
  useEffect(() => {
    const defaultId = index.data?.default_document_id;
    if (active && ownsIndexPermission() && defaultId && !documentId && draftController.pristineAuthoring && catalogue.sources.some(row => row.id === defaultId)) draftController.select(defaultId);
  }, [active, index.data, documentId]);
  // Persisted research descriptors carry their own exact verification inputs;
  // metadata refresh neither authenticates them nor restarts their pending GET.
  const exactRecovery = documentId.startsWith('research-version:') && recovery?.documentId === documentId && !!recovery.researchIdentity;
  const loadIndex = exactRecovery ? undefined : index.data;
  useEffect(() => {
    if (!ownsSession() || !active || (!exactRecovery && !loadIndex) || !documentId || documentId === NEW_DOCUMENT || !session || (document && loadedDocumentId === documentId)) return;
    if (!exactRecovery && !ownsIndexPermission()) return;
    const operation = draftController.beginLoad();
    if (!operation) return;
    let owned = true;
    const epoch = openEpoch.current;
    pendingIndexOpen.current = exactRecovery ? null : epoch;
    const ownsLoad = () => owned && ownsSession() && epoch === openEpoch.current
      && (exactRecovery || ownsIndexPermission()) && draftController.check(operation);
    setLoading(true);
    setError('');
    api
      .get<EditorDocument>(`/editor/documents/${encodeURIComponent(documentId)}`)
      .then(async (doc) => {
        if (!ownsLoad()) return;
        if (documentId.startsWith('research-version:') && recovery?.documentId === documentId && recovery.researchIdentity) {
          const identity = recovery.researchIdentity;
          await verifySource(doc, {id: documentId, kind: 'research_version', name: `${identity.family} v${identity.version}`, source: documentId, revision_id: identity.revision_id, source_hash: recovery.sourceHash, research_identity: identity,
            ...('kind' in identity.source ? {canonical_hash: identity.source.canonical_hash} : {})});
        } else if (index.data?.documents.find(row => row.id === documentId)?.kind || doc.source_origin || documentId.startsWith('editor-revision:')) {
          const source = catalogue.sources.find(row => row.id === documentId);
          if (!source) throw new Error('Exact source is absent or ambiguous in the catalogue.');
          await verifySource(doc, source);
        }
        if (ownsLoad()) {
          draftController.accept(documentId, doc, doc.yaml_text, { text: doc.yaml_text, result: doc.validation, owner: validationOwner(api, session.session_id, sessionGeneration, documentId, doc) }, operation);
        }
      })
      .catch((e) => {
        if (ownsLoad()) setError(e.message);
      })
      .finally(() => {
        if (pendingIndexOpen.current === epoch) pendingIndexOpen.current = null;
        if (owned && ownsSession() && epoch === openEpoch.current) setLoading(false);
      });
    return () => {
      owned = false;
      if (pendingIndexOpen.current === epoch) pendingIndexOpen.current = null;
    };
  }, [api, documentId, session?.session_id, sessionGeneration, active, loadIndex, exactRecovery, loadRequest]);
  async function validate(text = draft) {
    if (!ownsSession() || !active || !session || loading || loadedDocumentId !== documentId) return;
    retirePositionEdit();
    const sequence = ++request.current;
    const isCurrent = () => binding.current.active && binding.current.epoch === bindingEpoch && sequence === request.current && latest.current === text &&
      latestOwner.current === owner && ownsSession();
    setChecking(true);
    setError('');
    try {
      const result = await api.mutate<Validation>('/editor/validate', {
        yaml_text: text,
        ...(document ? { document_id: document.document_id } : {}),
      });
      if (isCurrent()) setValidation({ text, result, owner });
    } catch (e) {
      if (isCurrent()) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (isCurrent()) setChecking(false);
    }
  }
  useEffect(() => {
    setChecking(false);
    if (!active || !session || !draft || current || loading || loadedDocumentId !== documentId || !index.data) return;
    const timer = setTimeout(() => void validate(draft), 650);
    return () => {
      clearTimeout(timer);
      request.current++;
    };
  }, [api, draft, documentId, session?.session_id, sessionGeneration, loading, index.data, validation, active]);
  function chooseDocument(id: string) {
    const source = catalogue.sources.find(row => row.id === id);
    if (!source || !ownsAuthoringCommand() || renderedOpenEpoch !== openEpoch.current || !ownsCatalogueSource(source)) return;
    if (source && index.data?.documents.find(row => row.id === id)?.kind) { void openSource(source); return; }
    const operation = draftController.begin(draftHandler);
    if (!operation) return;
    if (
      (draftController.unboundAuthoring || draft !== (document?.yaml_text ?? '')) &&
      !window.confirm('Discard this unsaved draft and load another document?')
    )
      return;
    if (!ownsAuthoringCommand() || renderedOpenEpoch !== openEpoch.current || !ownsCatalogueSource(source) || !draftController.check(operation)) return;
    retirePositionEdit();
    request.current++;
    draftController.select(id, operation);
    setNumberedSource(undefined);
  }
  async function verifySource(doc: EditorDocument, source: SourceSummary) {
    if (!/^[a-f0-9]{32}$/.test(doc.document_id) || doc.source_origin?.kind !== source.kind || doc.source_origin.id !== source.id
      || typeof doc.yaml_text !== 'string' || doc.yaml_text.length > 262_144
      || !/^[a-f0-9]{64}$/.test(doc.source_hash) || doc.source_hash !== await editorSourceHash(doc.yaml_text)
      || doc.validation?.source_hash !== doc.source_hash
      || (source.source_hash !== undefined && doc.source_hash !== source.source_hash)
      || (source.canonical_hash !== undefined && doc.validation.canonical_hash !== source.canonical_hash)
      || (source.kind === 'editor_revision' && (source.id !== `editor-revision:${source.revision_id}` || !source.source_hash || !source.canonical_hash))
      || (source.kind === 'research_version' && !sameResearchIdentity(source.research_identity, doc.research_identity))) {
      throw new Error('Source identity or hash verification failed. No replacement or recent open recorded.');
    }
  }
  function ownsIndexPermission(capability?: 'research_version_open' | 'manual_research_save' | 'build' | 'policy_evaluation') {
    const state = cache.getQueryState<EditorIndex>(['editor', metadataOwner]);
    return ownsSession() && renderedCatalogueEpoch === catalogueEpoch.current && state?.status === 'success'
      && state.fetchStatus === 'idle' && !state.isInvalidated
      && (!capability || state.data?.capabilities[capability] === true);
  }
  function ownsCatalogueSource(source: SourceSummary) {
    return ownsIndexPermission(source.kind === 'research_version' ? 'research_version_open' : undefined)
      && normalizeLibrarySources(librarySources(cache.getQueryData<EditorIndex>(['editor', metadataOwner]))).sources.some(row => referenceKey(row) === referenceKey(source));
  }
  async function openSource(value: SourceSummary, authority: 'catalogue' | 'receipt' | 'research' = 'catalogue', researchAuthorized?: () => boolean) {
    if (!ownsSession() || (!active && !libraryActive) || renderedOpenAuthority !== openAuthority.current || renderedOpenEpoch !== openEpoch.current) return;
    const source = { ...value };
    // Detail authenticates immutable identity, not current editor-index admission.
    // Do not require mutable catalogue membership for the original research Open.
    const authorized = () => authority === 'receipt' || (authority === 'research'
      ? ownsIndexPermission('research_version_open') && researchAuthorized?.() === true : ownsCatalogueSource(source));
    if (!authorized()) return;
    const operation = draftController.begin(draftHandler);
    if (!operation) return;
    if ((draftController.unboundAuthoring || draft !== (document?.yaml_text ?? ''))
      && !window.confirm('Discard this unsaved draft and load another document?')) return;
    if (!ownsSession() || renderedOpenAuthority !== openAuthority.current || renderedOpenEpoch !== openEpoch.current || !authorized() || !draftController.check(operation)) return;
    setNumberedSource(undefined);
    retirePositionEdit(); request.current++;
    const epoch = ++openEpoch.current;
    pendingIndexOpen.current = authority !== 'receipt' ? epoch : null;
    const ownsOpen = () => editLifetime.current && ownsSession() && epoch === openEpoch.current;
    const isCurrent = () => ownsOpen() && authorized() && draftController.check(operation);
    setLoading(true); setError('');
    try {
      const doc = await api.get<EditorDocument>(`/editor/documents/${encodeURIComponent(source.id)}`);
      if (!isCurrent()) return;
      await verifySource(doc, source);
      if (!isCurrent()) return;
      if (!Number.isSafeInteger(openedSequence.current) || openedSequence.current >= Number.MAX_SAFE_INTEGER) throw new Error('Open sequence exhausted; reconnect explicitly.');
      if (!draftController.accept(source.id, doc, doc.yaml_text, { text: doc.yaml_text, result: doc.validation, owner: validationOwner(api, session!.session_id, sessionGeneration, source.id, doc) }, operation)) return;
      setOpened({ source, sequence: ++openedSequence.current, owner: metadataOwner });
      if (source.kind === 'research_version') setResearchInventory(current => ({owner: metadataOwner,
        sources: [source, ...(current.owner === metadataOwner ? current.sources.filter(row => row.id !== source.id) : [])].slice(0, LIBRARY_RECENT_LIMIT)}));
      setLoading(false);
      if (libraryActive) onLibraryOpened?.();
    } catch (e) { if (isCurrent()) setError(e instanceof Error ? e.message : 'Source open failed'); }
    finally {
      if (pendingIndexOpen.current === epoch) pendingIndexOpen.current = null;
      if (ownsOpen()) setLoading(false);
    }
  }
  function discardRecovery() {
    if (!ownsAuthoringCommand()) return;
    const unbound = draftController.unboundAuthoring;
    if (unbound && !window.confirm('Discard the stored backup and keep your current inputs as a detached new environment without source includes?')) return;
    if (!ownsAuthoringCommand()) return;
    if (draftController.discard(draftHandler, unbound ? 'detach-current-inputs' : 'keep-current-source')) retirePositionEdit();
  }
  const recoveryMatches = !!recovery && documentId === loadedDocumentId && recovery.documentId === loadedDocumentId && recovery.sourceHash === (document?.source_hash ?? '') && (
    recovery.researchIdentity ? document?.source_origin?.id === recovery.documentId && sameResearchIdentity(recovery.researchIdentity, document.research_identity)
      : recovery.viewId === (document?.document_id ?? NEW_DOCUMENT));
  return (
    <>
    <main id={libraryActive ? 'workspace' : undefined} hidden={!libraryActive} className="workspace">
      <EnvironmentLibrary key={metadataOwner} sources={libraryRows} selectedId={loadedDocumentId}
        sourcesStatus={libraryStatus} opened={opened?.owner === metadataOwner ? opened : undefined}
        onOpen={source => {
          const live = latestCatalogue.current;
          if (libraryActive && live.libraryStatus === 'ready' && live.catalogue.sources.some(row => referenceKey(row) === referenceKey(source))) void openSource(source);
        }} />
      <button type="button" disabled={!session || index.isFetching} onClick={() => void index.refetch()}>Refresh library</button>
      {loading && <p role="status">Opening exact source…</p>}
      {libraryActive && error && <p role="alert">{error}</p>}
    </main>
    <main id={active ? 'workspace' : undefined} hidden={!active} className={`workspace editor-workspace${v7 ? ' editor-v7' : ''}${v7 && expanded ? ' viewport-expanded' : ''}`}>
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
            {documentId === NEW_DOCUMENT && <option value={NEW_DOCUMENT}>New environment</option>}
            {document?.source_origin?.kind === 'research_version' && !catalogue.sources.some(row => row.id === documentId) && <option value={documentId}>{document.research_identity?.family} v{document.research_identity?.version} — frozen research version</option>}
            {catalogue.sources.map((doc) => (
              <option key={doc.id} value={doc.id}>
                {doc.name}
              </option>
            ))}
          </select>
        </label>
        <span className="source-path">
          {documentId === NEW_DOCUMENT ? 'Local new environment · no source includes' : document?.source ?? 'Connect to load an environment document'}
        </span>
        <span className="tag">
          {loading
            ? 'Loading…'
            : documentId === NEW_DOCUMENT || (document && draft !== document.yaml_text)
              ? 'Unsaved draft'
              : document
                ? 'Source loaded'
                : 'No document loaded'}
        </span>
      </div>
      {recovery && (
        <div className="notice warning" role="alert">
          <strong>Unsaved draft recovered from this tab</strong>
          <span>
            {recoveryMatches
              ? 'Restore it explicitly, or keep the source currently shown. No job will be restarted.'
              : 'The source or included YAML changed. Download your draft before discarding it; automatic context substitution is blocked.'}
          </span>
          <div className="editor-actions">
            <button disabled={loading || !ownsSession() || !recoveryMatches}
              onClick={() => {
                if (!ownsAuthoringCommand() || loading || !recoveryMatches) return;
                if (draftController.restore(draftHandler)) retirePositionEdit();
              }}>Restore draft</button>
            <button onClick={() => downloadRecoveredYaml(recovery.draft)}>Download recovered YAML</button>
            <button onClick={discardRecovery}>Discard recovered draft</button>
          </div>
        </div>
      )}
      {reconciliation && !recovery && <div className="notice warning" role="alert">
        <span>{draftController.storedBackup === null ? 'No stored backup was found. Explicitly keep current inputs to resume backups.' : 'The inspected stored backup cannot be decoded. Download it before explicitly discarding it.'}</span>
        {draftController.storedBackup !== null && <button type="button" onClick={() => downloadRecoveredYaml(draftController.storedBackup!, 'arena-stored-backup.json')}>Download stored backup</button>}
        <button type="button" onClick={discardRecovery}>{draftController.storedBackup === null ? 'Keep current draft backup' : 'Discard stored backup'}</button>
      </div>}
      {storageError && (
        <div className="notice warning" role="alert">
          <span>Browser draft storage is unavailable or this draft exceeds its limits. The current draft is not backed up. Export your YAML before reloading.</span>
          <span>{storageStatus === 'conflict' ? 'Stored backup changed; replacement is blocked until explicit review.' : storageStatus === 'invalid-record' ? 'Stored backup or current input is invalid or oversized; nothing is silently reset.' : 'Memory-only mode; storage recovery never automatically replays edits.'}</span>
          <button type="button" onClick={() => {if (ownsAuthoringCommand()) {draftController.review(draftHandler); retirePositionEdit();}}}>Review stored backup</button>
        </div>
      )}
      <button type="button" onClick={() => downloadRecoveredYaml(draft, 'arena-draft.yaml')}>Download current YAML</button>
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
      {active && modesAvailable && <MetadataBrowser />}
      {active && index.data?.capabilities.research_versions === true && <ResearchVersions candidate={generation.job} publicationExecution={index.data.capabilities.publication_execution === true}
        bindingKey={`${metadataOwner}:${documentId}:${document?.document_id ?? ''}:${openEpoch.current}`}
        isCurrent={() => ownsSession() && active && renderedOpenAuthority === openAuthority.current && renderedOpenEpoch === openEpoch.current}
        manualWriteAllowed={libraryStatus === 'ready' && index.data.capabilities.manual_research_save === true}
        isManualWriteCurrent={() => ownsIndexPermission('manual_research_save')}
        manualSource={index.data.capabilities.manual_research_save === true && numberedSource?.owner === metadataOwner && numberedSource.document === documentId && numberedSource.authority === renderedOpenAuthority ? numberedSource.source : undefined}
        isResearchOpenCurrent={() => ownsIndexPermission('research_version_open')}
        onResearchOpen={(source, authorized) => { void openSource(source, 'research', authorized); }} />}
      {v7 && <div className="editor-panel-controls" aria-label="Authoring panels">
        <button type="button" aria-expanded={generationOpen} onClick={() => setGenerationOpen(!generationOpen)}>{generationOpen ? 'Collapse generation' : 'Expand generation'}</button>
        <button type="button" aria-expanded={specificationOpen} onClick={() => setSpecificationOpen(!specificationOpen)}>{specificationOpen ? 'Collapse specification' : 'Expand specification'}</button>
        <button type="button" aria-expanded={inspectorOpen} onClick={() => setInspectorOpen(!inspectorOpen)}>{inspectorOpen ? 'Collapse inspector' : 'Expand inspector'}</button>
        <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? 'Restore panels' : 'Expand viewport'}</button>
      </div>}
      <div className="editor-grid">
        <div className="author-column">
          <section className="prompt-section" hidden={v7 && (!generationOpen || expanded)}>
            <div className="section-heading">
              <h2>Generate from prompt</h2>
              <span className="tag">Draft only · no Neo4j publication</span>
            </div>
            {active && (!v7 || (generationOpen && !expanded)) && <ModelSettings settings={modelSettings} />}
            {modesAvailable && <fieldset disabled={generation.busy || retryGeneration}>
              <legend>Generation mode</legend>
              <label><input type="radio" name="generation-mode" checked={selectedMode === 'new'}
                onChange={() => setGenerationMode('new')} />New environment from prompt</label>
              <label><input type="radio" name="generation-mode" checked={selectedMode === 'refine'}
                onChange={() => setGenerationMode('refine')} />Refine current environment</label>
              {selectedMode === 'new' && <label>Retrieval policy<select aria-label="Retrieval policy" value={selectedPolicy}
                onChange={(e) => setRetrievalPolicy(e.target.value === 'require_service' ? 'require_service' : 'allow_fallback')}>
                <option value="allow_fallback">Allow fallback when retrieval service is unavailable</option>
                <option value="require_service">Require read-only retrieval service</option>
              </select></label>}
              <p className="hint">GraphRAG retrieval evidence pending · no retrieval claimed.</p>
            </fieldset>}
            <label htmlFor="scene-prompt">Describe the environment and task</label>
            <textarea
              id="scene-prompt"
              rows={3}
              value={prompt}
              onChange={(e) => {if (!ownsInput()) return; retirePositionEdit(); draftController.edit({prompt: e.target.value}, draftHandler);}}
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
                  (!retryGeneration && ((loading && (!modesAvailable || generationMode !== 'new')) ||
                    (modesAvailable && generationMode === 'refine' && !valid))) ||
                  (!!recovery && !(generation.retained && !generation.job))
                }
                onClick={() =>
                  generation.submit.mutate({
                    prompt,
                    ...(modesAvailable ? { operation: generationMode, retrieval_policy: generationMode === 'new' ? retrievalPolicy : 'allow_fallback' } : {}),
                    ...(!modesAvailable || generationMode === 'refine' ? { base_yaml: draft,
                      ...(document ? { document_id: document.document_id } : {}) } : {}),
                    ...(modelSettings.credentialRef ? { credential_ref: modelSettings.credentialRef } : {}),
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
            {generated && cancelledCandidate && <p className="notice warning">Committed candidate from a cancelled job · job not successful. Review before applying; no outcome is inferred from receipts.</p>}
            {generated && <GenerationEvidence value={generated} />}
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
          <section className="yaml-section" ref={specification} hidden={v7 && (!specificationOpen || expanded)}>
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
            <CodeEditor label="YAML editor" value={draft} onChange={(text) => { if (!ownsInput() || text === latest.current) return; latest.current = text; retirePositionEdit(); draftController.edit({draft: text}, draftHandler); }} />
            <div className="editor-actions">
              <button
                disabled={!session || !index.data || !draft || checking}
                onClick={() => void validate()}
              >
                Validate schema
              </button>
              {!durableSave && <button
                disabled={!active || !session || !valid || save.isPending || loading || !!recovery}
                onClick={() => save.mutate({ yaml_text: draft, ...(document
                  ? { document_id: document.document_id, expected_source_hash: document.source_hash } : {}) })}
              >
                {save.isPending ? 'Saving…' : 'Save revision'}
              </button>}
            </div>
            {!durableSave && <p className="hint">Legacy save has no idempotent receipt recovery. If its response is lost, download current YAML before deciding whether to save again; another revision may be created.</p>}
            {durableSave && <EditorRevisionSave enabled={active && !!session && valid && !loading && !recovery}
              readEnabled={active && !!session}
              draft={draft} documentId={document?.document_id} expectedSourceHash={document?.source_hash}
              bindingKey={JSON.stringify([documentId, document?.document_id ?? null, document?.source_hash ?? null])}
              onSaved={revision => { if (ownsSession() && active) { savedRevision.current = revision; setNumberedSource({source: {kind: 'editor_revision', editor_revision_id: revision.revision_id, source_hash: revision.source_hash, canonical_hash: revision.canonical_hash}, owner: metadataOwner, document: documentId, authority: renderedOpenAuthority}); void index.refetch(); } }}
              onOpen={descriptor => {
                const revision = savedRevision.current;
                if (ownsSession() && active && revision?.open_source.id === descriptor.id) void openSource({
                  ...descriptor, revision_id: revision.revision_id, source_hash: revision.source_hash, canonical_hash: revision.canonical_hash,
                  name: `Editor revision ${revision.revision_id}`, source: descriptor.id,
                }, 'receipt');
              }} />}
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
          <EvaluationControls draft={draft} documentId={document?.document_id}
            enabled={valid && !checking && !error && !loading && !recovery}
            available={active && ownsIndexPermission('policy_evaluation')}
            canLaunch={() => ownsSnapshotControls() && draftController.eligible(draftHandler)}
            canDispatch={() => editLifetime.current && active && renderedOpenAuthority === openAuthority.current && ownsIndexPermission('policy_evaluation')} />
          <BuildControls draft={draft} documentId={document?.document_id}
            enabled={valid && !checking && !error && !loading && !recovery}
            available={active && ownsIndexPermission('build')}
            canLaunch={() => ownsSnapshotControls() && draftController.eligible(draftHandler)}
            canDispatch={() => editLifetime.current && active && renderedOpenAuthority === openAuthority.current && ownsIndexPermission('build')} />
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
                enabled={!!session && valid && !checking && !error && !loading && !recovery && index.data?.capabilities.snapshots === true}
              />
            </div>
            <div className="preview-options">
              <label>Preview mode<select aria-label="Preview mode" value={previewMode} onChange={(e) => { retirePositionEdit(); setPreviewMode(e.target.value); }}>
                <option value="assets">Assets</option><option value="scene">Scene</option>
              </select></label>
              <CameraSelect label="Scene camera" value={options.view} onChange={(view) => { retirePositionEdit(); setCameraOptions((old) => ({ ...old, view })); }} />
              <label>Image resolution<select aria-label="Image resolution" value={options.resolution} onChange={(e) => { retirePositionEdit(); setCameraOptions((old) => ({ ...old, resolution: Number(e.target.value) as 512 | 1024 })); }}>
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
            {active && (previewMode === 'assets' ? <AssetGrid
              assets={valid ? current.assets : []}
              receipt={snapshots.history[0]}
              stale={!snapshotMatches(snapshots.history[0], canonicalHash)}
              options={options}
              onCamera={(id, view) => { retirePositionEdit(); setCameraOptions((old) => {
                const asset_views = { ...old.asset_views };
                if (view) asset_views[id] = view; else delete asset_views[id];
                return { ...old, asset_views };
              }); }}
            /> : <SnapshotGallery snapshots={snapshots} canonicalHash={canonicalHash} />)}
            <div className="section-heading graph-heading">
              <h3>Authored spatial graph</h3>
              <span className="muted">Synchronized with validated YAML</span>
            </div>
            <GraphHost visible={active} graph={active && session && valid && !loading ? current.graph : null}
              scopeKey={`authored:${session?.session_id ?? 'expired'}:${document?.document_id ?? documentId}`}
              revisionKey={canonicalHash ?? ''} label="Authored spatial graph" sourceKind="authored"
              renderer={graphRenderer} onRendererChange={onGraphRendererChange} />
            {!valid && (
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
        <aside className="authored-inspector-panel" hidden={!v7 || !inspectorOpen || expanded} aria-label="Authored inspector">
          {renderInspector ? renderInspector(inspectorProps) : v7 ? <AuthoredInspector {...inspectorProps} /> : <p>Authored properties are available in the graph inspector below the snapshots.</p>}
          <p className="hint">Narrow root XYZ edits require candidate validation and explicit diff review. Numbered draft saves are not supported here. Raw YAML remains available; snapshots are not live simulation.</p>
        </aside>
      </div>
    </main>
    </>
  );
}
