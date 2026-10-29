import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  QueryClient,
  QueryClientProvider,
  skipToken,
  useMutation,
  useQuery,
} from '@tanstack/react-query';
import {
  Link,
  Outlet,
  RouterProvider,
  createRootRoute,
  createRoute,
  createRouter,
  useNavigate,
  useRouterState,
  type RouterHistory,
} from '@tanstack/react-router';
import { ApiClient } from './api';
import { ResearchServices } from './research-services';
import { QueueResume } from './queue-resume';
import { workspaceKey } from './cache';
import { isUnfinished, type Job, type Workspace } from './contracts';
import { sharedPort, type ObservationPort } from './observation';
import { RuntimeProvider, useRuntime } from './runtime';
import { EditorView } from './editor';
import { AuthoredInspector, type AuthoredInspectorProps } from './authored-inspector';
import { OptionalWorkbenchChrome } from './optional-workbench-chrome';
import { useJobCancellation } from './job-cancellation';
import { BuildOutcome } from './build-environment';
import { EvaluationOutcome } from './evaluate-policy';
import { GenerationReauthorization, isBlockedGeneration } from './generation-reauthorization';
import { GenerationDiagnostic } from './generation-diagnostic';
import { useModelSettings } from './model-settings';
import { Neo4jView } from './neo4j';
import { parseGraphRenderer, type GraphRendererChoice } from './graph-host';
import { ThemeProvider, ThemeToggle } from './theme';
import './styles.css';
import './editor.css';
import './theme.css';
import './layout-host.css';

interface WorkbenchSearch {
  filter: 'all' | 'active' | 'terminal';
  graphRenderer?: GraphRendererChoice;
  layout?: 'legacy' | 'v7';
}

const connectionLabels = {
  connecting: 'Connecting',
  live: 'Live · shared stream',
  reconnecting: 'Reconnecting stream',
  degraded: 'Degraded · status polling',
  expired: 'Session expired or revoked',
  disconnected: 'Disconnected',
};
const renderAuthoredInspector = (props: AuthoredInspectorProps) => <AuthoredInspector {...props} />;
function Shell() {
  const runtime = useRuntime();
  const { layout = 'legacy' } = rootRoute.useSearch();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: state => state.location.pathname });
  const editorActive = pathname === '/' || pathname === '/workspaces/default';
  const libraryActive = pathname === '/library';
  const queryActive = pathname === '/neo4j';
  const [visited, setVisited] = useState({ editor: editorActive || libraryActive, query: queryActive });
  useEffect(() => {
    setVisited(previous => previous.editor === (previous.editor || editorActive || libraryActive) && previous.query === (previous.query || queryActive)
      ? previous : { editor: previous.editor || editorActive || libraryActive, query: previous.query || queryActive });
  }, [editorActive, libraryActive, queryActive]);
  const graphProps = useGraphRouteProps();
  const endSession = useMutation({ mutationFn: runtime.revoke, retry: false });
  const presentation = useMemo(() => ({}), [layout]);
  const [readyFor, setReadyFor] = useState<object | null>(null);
  const [failedFor, setFailedFor] = useState<object | null>(null);
  const chromeReady = layout === 'v7' && readyFor === presentation;
  const chromeReadyCallback = useCallback(() => setReadyFor(presentation), [presentation]);
  const chromeFailureCallback = useCallback(() => {
    setReadyFor(previous => previous === presentation ? null : previous);
    setFailedFor(presentation);
  }, [presentation]);
  const sessionControls = <div className="session-controls">
    <button type="button" onClick={() => void navigate({ to: '.', search: (previous: WorkbenchSearch) => ({ ...previous, layout: layout === 'v7' ? 'legacy' : 'v7' }), replace: true })}>{layout === 'v7' ? 'Use legacy layout' : 'Try V7 layout'}</button>
    <span className={`connection ${runtime.status}`} role="status"><i />{connectionLabels[runtime.status]}</span>
    {runtime.session && <button className="quiet" disabled={endSession.isPending} onClick={() => endSession.mutate()}>End session</button>}
  </div>;
  const navigation = <nav aria-label="Workspace navigation">
    {([
      ['/workspaces/default', 'Environment editor', 'E'],
      ['/library', 'Library', 'L'],
      ['/neo4j', 'Neo4j query', 'Q'],
      ['/developer/diagnostics', 'Jobs & diagnostics', 'J'],
    ] as const).map(([to, label, marker]) => <Link key={to} to={to} title={label} className="nav-item"
      search={(previous: WorkbenchSearch) => previous} activeProps={{ className: 'nav-item selected' }}>
      <span className="workbench-nav-marker" aria-hidden="true">{marker}</span><span className="workbench-nav-label">{label}</span>
    </Link>)}
  </nav>;
  return (
    <div className={`app-shell${chromeReady ? ' workbench-v7' : ''}`}>
      <a className="skip-link" href="#workspace">
        Skip to workspace
      </a>
      <OptionalWorkbenchChrome enabled={layout === 'v7'} navigation={chromeReady ? navigation : null} sessionControls={chromeReady ? sessionControls : null}
        themeControl={chromeReady ? <ThemeToggle /> : null} onReady={chromeReadyCallback} onFailure={chromeFailureCallback} />
      <aside className="sidebar" hidden={chromeReady} style={chromeReady ? { display: 'none' } : undefined}>
        <div className="sidebar-brand-tools">
          <Link className="brand" to="/workspaces/default" search={(previous: WorkbenchSearch) => previous}>
            <span className="brand-mark" aria-hidden="true">
              A
            </span>
            <span>
              ARENA<small>Research workbench</small>
            </span>
          </Link>
        </div>
        <nav aria-label="Workspace navigation">
          <Link
            className="nav-item"
            to="/workspaces/default"
            search={(previous: WorkbenchSearch) => previous}
            activeProps={{ className: 'nav-item selected' }}
          >
            Environment editor
          </Link>
          <Link className="nav-item" to="/library" search={(previous: WorkbenchSearch) => previous} activeProps={{ className: 'nav-item selected' }}>Library</Link>
          <Link className="nav-item" to="/neo4j" search={(previous: WorkbenchSearch) => previous} activeProps={{ className: 'nav-item selected' }}>
            Neo4j query
          </Link>
          <Link
            className="nav-item"
            to="/developer/diagnostics"
            search={(previous: WorkbenchSearch) => previous}
            activeProps={{ className: 'nav-item selected' }}
          >
            Jobs & diagnostics
          </Link>
        </nav>
        <ThemeToggle />
      </aside>
      <div className="main-shell">
        <header className="topbar" hidden={chromeReady} style={chromeReady ? { display: 'none' } : undefined}>
          <span className="breadcrumb">
            Local research / <strong>default</strong>
          </span>
          {sessionControls}
        </header>
        <ResearchServices />
        {/* Global visibility; navigation still retires uncompleted resume intent. */}
        <QueueResume key={pathname} />
        {layout === 'v7' && failedFor === presentation && <p role="alert" className="notice warning">V7 layout unavailable. Legacy controls remain usable; no work was submitted by this layout change.</p>}
        {(runtime.error || endSession.error) && (
          <div className="notice error" role="alert">
            <strong>Connection or request problem</strong>
            <span>{runtime.error || endSession.error?.message}</span>
            <small>Existing jobs are not cancelled or replayed.</small>
          </div>
        )}
        {runtime.status === 'expired' && (
          <div className="notice warning" role="alert">
            Session expired or revoked. Jobs remain durable. Reconnect explicitly to inspect them;
            no job will be restarted.
          </div>
        )}
        {runtime.status !== 'live' && (
          <div className="transport-note">
            <span>
              Live observation is not available.{' '}
              {runtime.status === 'degraded'
                ? 'Status checks run every 5 seconds for active jobs, up to 60 attempts.'
                : 'The last snapshot may be stale.'}
            </span>
            <button disabled={runtime.connecting} onClick={() => void runtime.connect()}>
              {runtime.connecting ? 'Connecting…' : 'Reconnect session'}
            </button>
          </div>
        )}
        <div hidden={!editorActive && !libraryActive}>{(visited.editor || editorActive || libraryActive) && <EditorView {...graphProps} layout={chromeReady ? 'v7' : 'legacy'} active={editorActive} libraryActive={libraryActive} onLibraryOpened={() => void navigate({ to: '/workspaces/default', search: (previous: WorkbenchSearch) => previous })} renderInspector={renderAuthoredInspector} />}</div>
        <div hidden={!queryActive}>{(visited.query || queryActive) && <Neo4jView {...graphProps} active={queryActive} />}</div>
        <Outlet />
        <footer className="footer">
          <span>Arena · Environment research workbench</span>
          <span>Authored specifications and persisted query results stay separate.</span>
        </footer>
      </div>
    </div>
  );
}
function DiagnosticControls() {
  const runtime = useRuntime();
  const navigate = useNavigate();
  const [opted, setOpted] = useState(false);
  const [steps, setSteps] = useState(3);
  const [delay, setDelay] = useState(1);
  const [, rerender] = useState(0);
  const mutation = useMutation({
    retry: false,
    mutationFn: async () => {
      await runtime.api.activity();
      if (!runtime.pending) throw new Error('Browser request storage is unavailable');
      if (!runtime.pending.current) runtime.pending.prepare({ steps, delay_seconds: delay });
      return runtime.pending.submit(runtime.api);
    },
    onSuccess: async (job) => {
      await runtime.refresh();
      await navigate({ to: '/jobs/$jobId', params: { jobId: job.id }, search: (previous: WorkbenchSearch) => previous });
    },
    onSettled: () => rerender((n) => n + 1),
  });
  const available = runtime.health?.capabilities.diagnostic === true;
  const enabled =
    available && !!runtime.session && opted && !!runtime.pending && !mutation.isPending;
  const pending = runtime.pending?.current;
  return (
    <section className="panel diagnostic" aria-labelledby="diagnostic-heading">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">BOUNDED · TEST-ONLY</span>
          <h2 id="diagnostic-heading">Integration diagnostic</h2>
        </div>
        <span className="tag">
          {available
            ? 'Opt-in capability'
            : runtime.health
              ? 'Disabled by API'
              : 'Capability unknown'}
        </span>
      </div>
      <p className="muted">
        Exercise the queue, durable events and cancellation. This is not a robotics result.
      </p>
      {runtime.health && !available && (
        <p className="hint">
          The API must be started with <code>--diagnostics</code> before controls can be enabled.
        </p>
      )}
      {!runtime.health && (
        <p className="hint">Connect to the API to discover whether diagnostics are enabled.</p>
      )}
      <label className="consent">
        <input
          type="checkbox"
          checked={opted}
          disabled={!available || !runtime.session}
          onChange={(e) => setOpted(e.target.checked)}
        />
        Enable diagnostic controls for this tab
      </label>
      <div className="diagnostic-form">
        <label>
          Steps
          <input
            aria-label="Steps"
            type="number"
            min="1"
            max="10"
            step="1"
            value={pending?.inputs.steps ?? steps}
            disabled={!enabled || !!pending}
            onChange={(e) => setSteps(e.target.valueAsNumber)}
          />
        </label>
        <label>
          Delay per step (s)
          <input
            aria-label="Delay per step (s)"
            type="number"
            min="0.1"
            max="5"
            step="0.1"
            value={pending?.inputs.delay_seconds ?? delay}
            disabled={!enabled || !!pending}
            onChange={(e) => setDelay(e.target.valueAsNumber)}
          />
        </label>
        <button
          className="primary"
          disabled={
            !enabled ||
            !Number.isInteger(steps) ||
            steps < 1 ||
            steps > 10 ||
            !Number.isFinite(delay) ||
            delay < 0.1 ||
            delay > 5
          }
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending
            ? 'Submitting…'
            : pending
              ? 'Retry retained request'
              : 'Run integration test'}
        </button>
      </div>
      {pending && (
        <div className="notice warning">
          <strong>Unresolved submission retained</strong>
          <span>
            The server may have accepted this request. Retry sends the same key and frozen inputs,
            never a new job request.
          </span>
          <code className="request-key">{pending.idempotency_key}</code>
        </div>
      )}
      {mutation.error && (
        <p role="alert" className="error-text">
          {mutation.error.message}
        </p>
      )}
    </section>
  );
}
function StatusBadge({ job }: { job: Job }) {
  return <span className={`job-status ${job.status}`}>{job.status.replaceAll('_', ' ')}</span>;
}
function BlockedJobActions({ job, cancel }: { job: Job; cancel: ReturnType<typeof useJobCancellation>['cancel'] }) {
  useModelSettings(); // Reuse public, session-scoped settings observation on deep links.
  const runtime = useRuntime();

  return <>
    <GenerationReauthorization job={job} onVerified={runtime.refresh} />
    <button className="danger" disabled={!runtime.session || cancel.isPending} onClick={() => cancel.mutate()}>Cancel generation</button>
    {cancel.error && <p role="alert">{cancel.error.message}</p>}
  </>;
}
function JobInspector({ job }: { job?: Job }) {
  const runtime = useRuntime();
  const { cancel } = useJobCancellation(job?.id);
  if (!job)
    return (
      <section className="panel inspector empty">
        <div className="empty-icon" aria-hidden="true">
          ⌕
        </div>
        <h2>Inspect a job</h2>
        <p>Select a journal entry to inspect its frozen inputs and actual outcome.</p>
        <span className="tag">No synthetic results</span>
      </section>
    );
  return (
    <section className="panel inspector" aria-labelledby="inspector-heading">
      <div className="panel-heading">
        <h2 id="inspector-heading">Job details</h2>
        <StatusBadge job={job} />
      </div>
      <dl>
        <dt>Job ID</dt>
        <dd>
          <code>{job.id}</code>
        </dd>
        <dt>Kind</dt>
        <dd>{job.kind}</dd>
        <dt>Current stage</dt>
        <dd data-testid="job-stage">{job.stage}</dd>
        <dt>Created</dt>
        <dd>{formatTime(job.created_at)}</dd>
        <dt>Updated</dt>
        <dd>{formatTime(job.updated_at)}</dd>
        <dt>Submitted by session</dt>
        <dd>
          <code>{job.created_by_session_id}</code>
        </dd>
      </dl>
      <h3>Frozen inputs</h3>
      <pre>{JSON.stringify(job.inputs, null, 2)}</pre>
      <h3>Job outcome</h3>
      <BuildOutcome job={job} />
      <EvaluationOutcome job={job} />
      {job.kind === 'generate' && <GenerationDiagnostic value={job.diagnostic} />}
      {job.kind === 'evaluate' && job.result ? null : job.result ? (
        <pre data-testid="job-result">{JSON.stringify(job.result, null, 2)}</pre>
      ) : (
        <p className="muted">No completion result recorded.</p>
      )}
      {job.error && (
        <p role="alert" className="error-text">
          {job.error}
        </p>
      )}
      {job.status === 'indeterminate' && (
        <p className="notice warning">
          No verified completion was recorded. {job.kind === 'generate' && !job.diagnostic ? 'A specific cause was not retained for this attempt. ' : ''}This job will not be automatically replayed.
        </p>
      )}
      {job.status === 'cancel_requested' && (
        <p className="notice warning">
          Cancellation requested. Waiting for worker cleanup acknowledgment; not yet cancelled.
        </p>
      )}
      {isBlockedGeneration(job) && <BlockedJobActions key={job.id} job={job} cancel={cancel} />}
      {['queued', 'running'].includes(job.status) && (
        <button
          className="danger"
          disabled={!runtime.session || cancel.isPending}
          onClick={() => cancel.mutate()}
        >
          Request cancellation
        </button>
      )}
      {cancel.error && (
        <p role="alert" className="error-text">
          {cancel.error.message} Refresh status before another cancellation request.
        </p>
      )}
    </section>
  );
}
function formatTime(value: number | string) {
  const date = new Date(typeof value === 'number' ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? 'Not reported' : date.toLocaleString();
}
function WorkspaceView({ selectedJobId }: { selectedJobId?: string }) {
  const runtime = useRuntime();
  const navigate = useNavigate();
  const { filter } = rootRoute.useSearch();
  const { data: workspace } = useQuery<Workspace>({
    queryKey: workspaceKey,
    queryFn: skipToken,
    staleTime: Infinity,
  });
  const jobs = [...(workspace?.jobs ?? [])].sort(
    (a, b) => String(b.created_at).localeCompare(String(a.created_at)) || a.id.localeCompare(b.id),
  );
  const visible = jobs.filter(
    (j) => filter === 'all' || (filter === 'active' ? isUnfinished(j) : !isUnfinished(j)),
  );
  const selected = jobs.find((j) => j.id === selectedJobId);
  return (
    <main id="workspace" className="workspace">
      <div className="page-heading">
        <div>
          <span className="eyebrow">WORKSPACE / DEFAULT</span>
          <h1>{workspace?.name ?? 'Arena workspace'}</h1>
          <p>Durable jobs and runtime observation</p>
        </div>
        <button disabled={!runtime.session} onClick={() => void runtime.refresh()}>
          Refresh snapshot
        </button>
      </div>
      <div className="scope-note">
        <strong>Integration gate</strong>
        <span>Validate transport and job lifecycle before enabling research workloads.</span>
        <span className="tag">Viewing does not start work</span>
      </div>
      <DiagnosticControls />
      <div className="work-grid">
        <section className="panel jobs-panel" aria-labelledby="jobs-heading">
          <div className="panel-heading">
            <h2 id="jobs-heading">
              Job journal <span className="count">{workspace ? jobs.length : '—'}</span>
            </h2>
            <label className="filter-label">
              Show
              <select
                aria-label="Filter jobs"
                value={filter}
                onChange={(e) =>
                  void navigate({
                    to: '.',
                    search: (previous: WorkbenchSearch) => ({ ...previous, filter: e.target.value as 'all' | 'active' | 'terminal' }),
                  })
                }
              >
                <option value="all">All jobs</option>
                <option value="active">Unfinished (including authorization waits)</option>
                <option value="terminal">Terminal</option>
              </select>
            </label>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Status</th>
                  <th>Stage</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((job) => (
                  <tr key={job.id} className={selectedJobId === job.id ? 'selected-row' : ''}>
                    <td>
                      <Link to="/jobs/$jobId" params={{ jobId: job.id }} search={(previous: WorkbenchSearch) => previous}>
                        <strong>{job.kind === 'diagnostic' ? 'Integration test' : job.kind}</strong>
                        <code>{job.id}</code>
                      </Link>
                    </td>
                    <td>
                      <StatusBadge job={job} />
                    </td>
                    <td>{job.stage}</td>
                    <td className="timestamp">{formatTime(job.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {visible.length === 0 && (
            <div className="empty journal-empty">
              <h3>
                {!workspace
                  ? 'Workspace snapshot unavailable'
                  : jobs.length
                    ? 'No jobs match this filter'
                    : 'No jobs recorded'}
              </h3>
              <p>
                {!workspace
                  ? 'Connect to the API to read durable state. No results are inferred while disconnected.'
                  : 'Jobs appear here only after an explicit submission. Refreshing or changing routes never starts work.'}
              </p>
            </div>
          )}
          <div className="panel-foot">
            Snapshot cursor <code>{workspace?.event_cursor ?? 'unknown'}</code>
            <span>Server-owned state</span>
          </div>
        </section>
        {selectedJobId && workspace && !selected ? (
          <section className="panel inspector empty">
            <h2>Job not found</h2>
            <p>This ID is absent from the current workspace snapshot.</p>
            <Link to="/developer/diagnostics" search={(previous: WorkbenchSearch) => previous}>Return to journal</Link>
          </section>
        ) : (
          <JobInspector key={selectedJobId ?? 'empty'} job={selected} />
        )}
      </div>
    </main>
  );
}
function useGraphRouteProps() {
  const { graphRenderer } = rootRoute.useSearch();
  const navigate = useNavigate();
  return {
    graphRenderer: parseGraphRenderer(graphRenderer),
    onGraphRendererChange: (renderer: GraphRendererChoice) => { void navigate({ to: '.', search: (previous: WorkbenchSearch) => ({ ...previous, graphRenderer: renderer }), replace: true }); },
  };
}
function EditorRoute() { return null; }
function Neo4jRoute() { return null; }
const rootRoute = createRootRoute({
  component: Shell,
  validateSearch: (search: Record<string, unknown>): WorkbenchSearch => ({
    filter:
      search.filter === 'active' || search.filter === 'terminal' ? search.filter : ('all' as const),
    ...(search.graphRenderer === undefined ? {} : { graphRenderer: parseGraphRenderer(search.graphRenderer) }),
    ...(search.layout === undefined ? {} : { layout: search.layout === 'v7' ? 'v7' : 'legacy' }),
  }),
  notFoundComponent: () => (
    <main className="workspace">
      <h1>Route not found</h1>
      <Link to="/workspaces/default" search={(previous: WorkbenchSearch) => previous}>Open workspace</Link>
    </main>
  ),
});
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: EditorRoute,
});
const workspaceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/workspaces/default',
  component: EditorRoute,
});
const diagnosticsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/developer/diagnostics',
  component: WorkspaceView,
});
const jobRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/jobs/$jobId',
  component: () => <WorkspaceView selectedJobId={jobRoute.useParams().jobId} />,
});
const neo4jRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/neo4j',
  component: Neo4jRoute,
});
const libraryRoute = createRoute({ getParentRoute: () => rootRoute, path: '/library', component: EditorRoute });
const routeTree = rootRoute.addChildren([
  libraryRoute,
  indexRoute,
  workspaceRoute,
  jobRoute,
  diagnosticsRoute,
  neo4jRoute,
]);
export function App({
  api,
  cache,
  history,
  makePort = sharedPort,
}: {
  api: ApiClient;
  cache: QueryClient;
  history?: RouterHistory;
  makePort?: () => ObservationPort | null;
}) {
  const router = useMemo(
    () => createRouter({ routeTree, history, defaultPreload: false, defaultPendingMinMs: 0 }),
    [history],
  );
  return (
    <ThemeProvider>
      <QueryClientProvider client={cache}>
        <RuntimeProvider api={api} makePort={makePort}>
          <RouterProvider router={router} />
        </RuntimeProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
