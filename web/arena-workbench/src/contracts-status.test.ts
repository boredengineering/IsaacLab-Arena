import { expect, it } from 'vitest';
import { isActive, isUnfinished, type Job } from './contracts';

it('distinguishes unfinished authorization waits from active execution and terminal results', () => {
 const job = { status: 'blocked_authorization' } as Job;
 expect(isActive(job)).toBe(false);
 expect(isUnfinished(job)).toBe(true);
 for (const status of ['succeeded', 'failed', 'cancelled', 'indeterminate'] as const) expect(isUnfinished({ ...job, status })).toBe(false);
});
