import { isEvent, isWorkspace, type JobEvent, type Workspace } from './contracts';

/** Attach the event listener before fetching a consistent snapshot. Never use wall clocks for ordering. */
export class Reconciler {
  value: Workspace | undefined;
  needsResync = false;
  private buffer = new Map<number, JobEvent>();
  get bufferedCount() {
    return this.buffer.size;
  }

  event(raw: unknown) {
    if (!isEvent(raw)) {
      this.needsResync = true;
      return;
    }
    if (this.value && raw.id <= this.value.event_cursor) return;
    this.buffer.set(raw.id, raw);
    if (this.buffer.size > 256) {
      this.buffer.clear();
      this.needsResync = true;
      return;
    }
    this.drain();
  }

  snapshot(raw: unknown) {
    if (!isWorkspace(raw)) throw new Error('Invalid workspace snapshot');
    if (this.value && raw.event_cursor < this.value.event_cursor) return;
    this.value = raw;
    this.needsResync = false;
    for (const id of this.buffer.keys()) if (id <= raw.event_cursor) this.buffer.delete(id);
    this.drain();
  }

  private drain() {
    if (!this.value) return;
    for (const [id, event] of [...this.buffer].sort(([a], [b]) => a - b)) {
      if (id !== this.value.event_cursor + 1) {
        this.needsResync = true;
        return;
      }
      this.value = {
        ...this.value,
        event_cursor: id,
        jobs: [...this.value.jobs.filter((j) => j.id !== event.job_id), event.job],
      };
      this.buffer.delete(id);
    }
    this.needsResync = false;
  }
}
