/** Local design-preview contracts; never sent to a production API. */
export type PreviewSection = 'environment' | 'library' | 'visualizer' | 'build' | 'improve' | 'experiments' | 'runs' | 'neo4j' | 'graph' | 'jobs' | 'settings' | 'coverage';

export interface PreviewSelection {
  familyId: string;
  familyName: string;
  versionId: string;
  version: number;
  source: string;
  yaml: string;
  robot: string;
  hand: string;
}

export interface PreviewContext {
  familyId: string | null;
  versionId: string | null;
  familyName: string;
  versionLabel: string;
  robot: string;
  hand: string;
  dirty: boolean;
}
