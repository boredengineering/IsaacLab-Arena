/** Upstream owns teardown, but its scene destructor and deferred data digest
 * both traverse custom objects. Make the resource's actual disposal idempotent. */
export function upstreamOwnedResource<T extends {dispose(): void}>(resource:T):T {
  const dispose=resource.dispose.bind(resource);let disposed=false;
  resource.dispose=()=>{if(!disposed){disposed=true;dispose();}};
  return resource;
}

/** One owner per resource collection; React's synchronous effect probe is not an unmount. */
export function resourceLifetime(dispose: () => void): () => () => void {
  let generation = 0;
  let disposed = false;
  return () => {
    const current = ++generation;
    return () => queueMicrotask(() => {
      if (current === generation && !disposed) { disposed = true; dispose(); }
    });
  };
}
