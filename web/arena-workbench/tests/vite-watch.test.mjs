import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { createServer, loadConfigFromFile } from 'vite';

const loaded = await loadConfigFromFile(
  { command: 'serve', mode: 'development' },
  resolve('vite.config.ts'),
  process.cwd(),
  'silent',
  undefined,
  'runner',
);

async function waitFor(predicate) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  assert.fail('Timed out waiting for the live source watcher');
}

test('development watches source but does not descend into retained test artifacts', async () => {
  const root = await mkdtemp(join(tmpdir(), 'arena-vite-watch-'));
  const archives = ['tests/e2e/functional-v7/.runs/retained/source/src', 'test-results', 'playwright-report'];
  let server;
  try {
    for (const directory of ['src', ...archives]) {
      await mkdir(join(root, directory), { recursive: true });
      await writeFile(join(root, directory, 'example.ts'), 'export const value = 1;\n');
    }
    server = await createServer({
      configFile: false,
      envFile: false,
      root,
      cacheDir: join(root, '.cache'),
      logLevel: 'silent',
      server: { ...loaded.config.server, middlewareMode: true },
    });
    await waitFor(() => server.watcher.getWatched()[join(root, 'src')]?.includes('example.ts'));
    const watched = Object.keys(server.watcher.getWatched());
    for (const directory of archives) {
      assert.equal(watched.some(path => path === join(root, directory)), false, `Archive watched: ${directory}`);
    }
    let changed = false;
    server.watcher.on('change', path => { if (path === join(root, 'src/example.ts')) changed = true; });
    await writeFile(join(root, 'src/example.ts'), 'export const value = 2;\n');
    await waitFor(() => changed);
  } finally {
    await server?.close();
    await rm(root, { recursive: true, force: true });
  }
});
