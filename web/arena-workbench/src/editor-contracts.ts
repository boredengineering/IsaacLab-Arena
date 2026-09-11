export interface GraphNode {
  id: string;
  label: string;
  role: string;
  properties: Record<string, unknown>;
}
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  properties: Record<string, unknown>;
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
  documents: { id: string; name: string; source: string }[];
  capabilities: { generation: boolean; snapshots: boolean; neo4j: boolean };
  limitations: string[];
}
export interface EditorDocument {
  document_id: string;
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
export interface SnapshotResult {
  input_hash: string;
  assets: { id: string; artifact_id: string; url: string; dimensions_m?: number[] }[];
  scene: { artifact_id: string; url: string } | null;
  warnings: string[];
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
