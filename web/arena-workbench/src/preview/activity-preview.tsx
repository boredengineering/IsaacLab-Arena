import React, { useId, useState } from 'react';
import { exampleJobSummaries } from './jobs-diagnostics';

type ActivityPreviewProps = {
  onInspectJob: (id: string) => void;
  onOpenEvidence: () => void;
};

export function ActivityPreview({ onInspectJob, onOpenEvidence }: ActivityPreviewProps) {
  const listId = useId();
  const [expanded, setExpanded] = useState(false);
  return <section className="preview-panel preview-activity" aria-label="Activity preview">
    <h2>Activity</h2>
    <p className="preview-activity-banner">Static example fixtures — Disconnected. No live activity or runtime authority.</p>
    <p className="preview-muted">These are not accepted jobs and are not associated with the current draft or historical images.</p>
    <dl className="preview-activity-counts">
      <div><dt>Active examples</dt><dd aria-label="Active example jobs">{exampleJobSummaries.filter(job => job.isActive).length}</dd></div>
      <div><dt>Attention examples</dt><dd aria-label="Attention example jobs">{exampleJobSummaries.filter(job => job.needsAttention).length}</dd></div>
    </dl>
    <p className="preview-muted">Counts overlap. Active includes blocked and cleanup-pending; attention includes those plus indeterminate and failed examples.</p>
    <button type="button" aria-expanded={expanded} aria-controls={listId} onClick={() => setExpanded(value => !value)}>{expanded ? 'Hide example jobs' : 'Show example jobs'}</button>
    <ul id={listId} className="preview-activity-jobs" aria-label="Activity example jobs" hidden={!expanded}>
      {exampleJobSummaries.map(job => <li key={job.id}>
        <button type="button" className="preview-activity-job-link" aria-label={`Inspect ${job.id}`} onClick={() => onInspectJob(job.id)}>{job.id}</button>
        <span>{job.statusLabel}</span>
      </li>)}
    </ul>
    <div className="preview-activity-evidence">
      <p className="preview-muted">Independent research examples — not proven artifacts of these jobs.</p>
      <button type="button" onClick={() => onOpenEvidence()}>Open independent research examples</button>
    </div>
  </section>;
}
