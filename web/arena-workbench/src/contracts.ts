/** Durable transport contract shared by diagnostic and editor jobs. */
export const statuses = [
  'queued',
  'running',
  'cancel_requested',
  'succeeded',
  'failed',
  'cancelled',
  'indeterminate',
] as const;
export type JobStatus = (typeof statuses)[number];
export interface Job {
  id: string;
  workspace_id: string;
  kind: string;
  status: JobStatus;
  stage: string;
  created_at: number | string;
  updated_at: number | string;
  inputs: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  created_by_session_id: string;
}
export interface Workspace {
  id: string;
  name: string;
  jobs: Job[];
  event_cursor: number;
}
export interface JobEvent {
  schema_version: 1;
  id: number;
  workspace_id: string;
  job_id: string;
  kind: string;
  job: Job;
}
export interface Session {
  session_id: string;
  csrf_token: string;
  expires_at: number;
}
export interface Health {
  status: string;
  capabilities: { diagnostic: boolean; generation: false; preview: false };
}
export interface JobRequest {
  workspace_id: 'default';
  kind: 'diagnostic';
  idempotency_key: string;
  inputs: { steps: number; delay_seconds: number };
}
export const isActive = (job: Job) =>
  ['queued', 'running', 'cancel_requested'].includes(job.status);
export function isJob(value: unknown): value is Job {
  if (!value || typeof value !== 'object') return false;
  const j = value as Job;
  return (
    typeof j.id === 'string' &&
    j.workspace_id === 'default' &&
    typeof j.stage === 'string' &&
    statuses.includes(j.status) &&
    typeof j.kind === 'string' &&
    !!j.inputs &&
    typeof j.inputs === 'object' &&
    !Array.isArray(j.inputs) &&
    (j.kind !== 'diagnostic' ||
      (typeof j.inputs.steps === 'number' && typeof j.inputs.delay_seconds === 'number'))
  );
}
export function isEvent(value: unknown): value is JobEvent {
  if (!value || typeof value !== 'object') return false;
  const e = value as JobEvent;
  return (
    e.schema_version === 1 &&
    Number.isSafeInteger(e.id) &&
    e.id > 0 &&
    e.workspace_id === 'default' &&
    typeof e.kind === 'string' &&
    isJob(e.job) &&
    e.job_id === e.job.id
  );
}
export function isWorkspace(value: unknown): value is Workspace {
  if (!value || typeof value !== 'object') return false;
  const s = value as Workspace;
  return (
    s.id === 'default' &&
    typeof s.name === 'string' &&
    Number.isSafeInteger(s.event_cursor) &&
    s.event_cursor >= 0 &&
    Array.isArray(s.jobs) &&
    s.jobs.every(isJob)
  );
}
