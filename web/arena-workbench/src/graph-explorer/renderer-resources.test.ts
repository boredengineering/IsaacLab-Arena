import { expect, it } from 'vitest';
import { resourceLifetime, upstreamOwnedResource } from './renderer-resources';
import { BufferGeometry } from 'three';
it('lets upstream recursive teardown dispose a custom resource exactly once',()=>{
  const geometry=new BufferGeometry();let disposed=0;geometry.addEventListener('dispose',()=>disposed++);
  expect(upstreamOwnedResource(geometry)).toBe(geometry);
  geometry.dispose();geometry.dispose();expect(disposed).toBe(1);
});
it('cancels StrictMode probe disposal but disposes replaced and unmounted resource owners', async () => {
  let disposed=0;const owner=resourceLifetime(()=>{disposed++;});
  const probe=owner();probe();const real=owner();await Promise.resolve();expect(disposed).toBe(0);
  real();await Promise.resolve();expect(disposed).toBe(1);
});
