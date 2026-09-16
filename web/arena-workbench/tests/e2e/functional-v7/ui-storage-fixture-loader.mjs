// Copyright (c) 2026, The Isaac Lab Arena Project Developers.
// SPDX-License-Identifier: Apache-2.0
// Import-safe builtin-only route/byte confinement; never imports browser packages.
import assert from 'node:assert/strict';
import { constants } from 'node:fs';
import { lstat, open, readdir } from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
export const ORIGIN = 'http://127.0.0.1:31847';
export const MAX_ASSET_BYTES = 4 * 1024 * 1024;
const ASSETS = Object.freeze({ 'fixture.html': 'text/html', 'fixture.js': 'text/javascript', 'fixture.css': 'text/css' });
export function fixturePath(method, url) {
  if (method !== 'GET') return null;
  if (url === ORIGIN + '/') return 'fixture.html';
  return Object.keys(ASSETS).find(name => name !== 'fixture.html' && url === ORIGIN + '/' + name) ?? null;
}
const identity = stat => [stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs, stat.nlink].join(':');
export const sameDirectory = (left, right) => left.dev === right.dev && left.ino === right.ino;
export async function closeHandles(handles) {
  let failure;
  for (const handle of [...handles].reverse()) {
    try { await handle.close(); } catch (error) { failure ??= error; }
  }
  if (failure) throw failure;
}
export async function loadFixture(root) {
  assert(path.isAbsolute(root) && path.normalize(root) === root, 'lexical absolute fixture root required');
  // Hold each physical directory descriptor; use /proc/self/fd for relative reads.
  // This is Linux-only by design, inside the owned immutable-image sandbox.
  const handles = [], links = [];
  const flags = constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW;
  try {
    handles.push(await open('/', flags));
    for (const part of root.split('/').filter(Boolean)) {
      const name = `/proc/self/fd/${handles.at(-1).fd}/${part}`;
      const before = await lstat(name, { bigint: true });
      assert(before.isDirectory(), 'physical directory required');
      const handle = await open(name, flags);
      handles.push(handle);
      assert(sameDirectory(await handle.stat({ bigint: true }), before), 'directory replaced');
      links.push([name, before.dev, before.ino]);
    }
    const anchored = `/proc/self/fd/${handles.at(-1).fd}`;
    assert.deepEqual((await readdir(anchored)).sort(), Object.keys(ASSETS).sort(), 'exact fixture file allowlist');
    const result = new Map(); let total = 0;
    for (const [name, mime] of Object.entries(ASSETS)) {
      const filename = anchored + '/' + name;
      const before = await lstat(filename, { bigint: true });
      assert(before.isFile(), 'physical regular file required');
      assert.equal(before.nlink, 1n, 'singly-linked file required');
      assert(before.size > 0n && before.size <= BigInt(MAX_ASSET_BYTES), 'asset byte budget');
      const handle = await open(filename, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
      try {
        assert.equal(identity(await handle.stat({ bigint: true })), identity(before), 'file replaced');
        const bytes = Buffer.alloc(Number(before.size) + 1);
        let length = 0;
        while (length < bytes.length) {
          const read = await handle.read(bytes, length, bytes.length - length, length);
          if (!read.bytesRead) break;
          length += read.bytesRead;
        }
        assert.equal(length, Number(before.size), 'file changed during bounded read');
        assert.equal(identity(await handle.stat({ bigint: true })), identity(before), 'file changed');
        assert.equal(identity(await lstat(filename, { bigint: true })), identity(before), 'file replaced');
        const captured = bytes.subarray(0, length);
        total += length; assert(total <= 8 * 1024 * 1024, 'aggregate fixture budget');
        result.set(name, { bytes: captured, mime, sha256: createHash('sha256').update(captured).digest('hex') });
      } finally { await handle.close(); }
    }
    for (const [name, dev, ino] of links) {
      const stat = await lstat(name, { bigint: true });
      assert(stat.isDirectory() && stat.dev === dev && stat.ino === ino, 'directory replaced');
    }
    return result;
  } finally { await closeHandles(handles); }
}
export async function installFixtureRoutes(context, fixture, rejected, audit = {}) {
  const record = value => {
    // Latch overflow without throwing before the request is settled.
    if (rejected.length >= 128) { audit.overflow = true; return; }
    rejected.push(value);
  };
  await context.route('**/*', async route => {
    const request = route.request(), name = fixturePath(request.method(), request.url());
    if (!name || !fixture.has(name)) {
      try { record({ method: request.method().slice(0, 16), url: request.url().slice(0, 2048) }); }
      finally { await route.abort('blockedbyclient'); }
      return;
    }
    const asset = fixture.get(name);
    return route.fulfill({ status: 200, contentType: asset.mime, body: asset.bytes,
      headers: { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'none'; worker-src 'none'; img-src 'none'; base-uri 'none'; form-action 'none'" } });
  });
  await context.routeWebSocket('**/*', async socket => {
    try { record({ method: 'WEBSOCKET', url: socket.url().slice(0, 2048) }); }
    finally { await socket.close(); }
  });
}
