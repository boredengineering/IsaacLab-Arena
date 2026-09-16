/** JSON wire values include whole-property truncation/redaction sentinels. */
export type JSONValue = null | boolean | number | string | readonly JSONValue[] | { readonly [key: string]: JSONValue };

/** Compile-time wire shape only; normalize unknown API data before graph exploration. */
export interface GraphNode {
  id: string;
  label: string;
  role: string;
  labels?: readonly string[];
  properties: JSONValue;
}
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  properties: JSONValue;
}
export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}
export interface Asset {
  id: string;
  role: string;
  registry_name?: string;
  parent_id?: string;
  prim_path?: string;
  properties: Record<string, unknown>;
}
export interface Validation {
  valid: boolean;
  source_hash: string;
  canonical_hash: string | null;
  errors: string[];
  warnings: string[];
  spec: Record<string, unknown> | null;
  summary: string;
  graph: Graph;
  assets: Asset[];
  relations: Record<string, unknown>[];
  reified_relations: Record<string, unknown>[];
  tasks: Record<string, unknown>[];
}
export interface EditorIndex {
  default_document_id: string;
  documents: { id: string; name: string; source: string; kind?: 'discovered_file' | 'editor_revision'; revision_id?: string; source_hash?: string; canonical_hash?: string }[];
  capabilities: { generation: boolean; snapshots: boolean; neo4j: boolean; build?: boolean; policy_evaluation?: boolean; generation_modes?: boolean; workflow_readiness?: boolean; research_versions?: boolean; publication_execution?: boolean; manual_research_save?: boolean; research_version_open?: boolean };
  limitations: string[];
}
export interface EditorDocument {
  document_id: string;
  source_origin?: { kind: 'discovered_file' | 'editor_revision' | 'research_version'; id: string };
  research_identity?: import('./research-source').ResearchIdentity;
  source: string;
  yaml_text: string;
  source_hash: string;
  validation: Validation;
}
export interface Revision {
  revision_id: string;
  yaml_text: string;
  source_hash: string;
  canonical_hash: string;
  download_url: string;
}
export type CameraView = 'isometric' | 'front' | 'side' | 'top';
export interface RenderOptions {
  view: CameraView;
  resolution: 512 | 1024;
  asset_views: Record<string, CameraView>;
}
export interface SnapshotArtifact {
  artifact_id: string;
  url: string;
  variants?: {
    thumbnail: { artifact_id: string; url: string; width: number; height: number };
    full: { artifact_id: string; url: string; width: number; height: number };
  };
}
export interface SnapshotResult {
  input_hash?: string;
  canonical_hash?: string;
  cache_key?: string;
  renderer_version?: string;
  freshness?: 'verified_assets' | 'unverified_assets';
  options?: RenderOptions;
  assets: (SnapshotArtifact & { id: string; dimensions_m?: number[] })[];
  scene: SnapshotArtifact | null;
  warnings: string[];
  errors?: { id: string; stage: string; code: string; message: string }[];
  partial?: boolean;
  timings?: Record<string, number>;
}
export interface PreviewLookup {
  status: 'hit' | 'historical' | 'miss';
  canonical_hash: string;
  receipt: SnapshotResult | null;
}
export interface BuildResult {
  schema_version: 1;
  input_hash: string;
  canonical_hash: string;
  headless: true;
  num_envs: 1;
  num_steps: 20;
  policy: 'zero_action';
  completed: true;
}
export interface GeneratedResult {
  yaml_text: string;
  validation: Validation;
  traces: string[];
  publication: 'not_published';
  warnings: string[];
}
export interface QueryResult {
  columns: string[];
  rows: unknown[][];
  graph: Graph;
  truncated: boolean;
  elapsed_ms: number;
  read_only: true;
}
