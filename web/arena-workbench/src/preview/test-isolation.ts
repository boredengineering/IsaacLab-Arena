/** Defense in depth; OS network denial is established before Vitest starts. */
import { beforeEach, vi } from 'vitest';
beforeEach(() => {
  const deny = () => { throw new Error('Network access is forbidden in the design preview'); };
  vi.stubGlobal('fetch', vi.fn(deny));
  vi.stubGlobal('WebSocket', class { constructor() { deny(); } });
  vi.stubGlobal('EventSource', class { constructor() { deny(); } });
  vi.stubGlobal('Worker', class { constructor() { deny(); } });
  vi.stubGlobal('SharedWorker', class { constructor() { deny(); } });
  vi.stubGlobal('RTCPeerConnection', class { constructor() { deny(); } });
  for (const method of ['getItem', 'setItem', 'removeItem', 'clear', 'key'] as const) vi.spyOn(Storage.prototype, method).mockImplementation(() => { throw new Error('Browser storage is forbidden in the design preview'); });
  vi.spyOn(XMLHttpRequest.prototype, 'open').mockImplementation(deny);
});
