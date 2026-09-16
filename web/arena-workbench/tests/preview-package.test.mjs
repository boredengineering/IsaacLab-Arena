import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, symlink, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

async function fixture() {
 const root = await mkdtemp(join(tmpdir(), 'preview-package-test-'));
 const build = join(root, 'build'); await mkdir(build);
 await writeFile(join(build, 'preview.html'), '<meta content="script-src \'self\'; connect-src \'none\'"><script type="module" src="./bundle.js"></script><link rel="stylesheet" href="./style.css">');
 await writeFile(join(build, 'style.css'), 'body {color: black}');
 await writeFile(join(build, 'bundle.js'), 'console.log("example only");');
 return { root, build };
}
const run = build => spawnSync(process.execPath, [resolve('scripts/package-preview.mjs'), build], { encoding: 'utf8' });
test('normal preview bundle becomes a hash-bound offline artifact', async () => {
 const { root, build } = await fixture();
 try { const result = run(build); assert.equal(result.status, 0, result.stderr); assert.match(await readFile(join(build, 'arena-workflow-preview.html'), 'utf8'), /script-src 'sha256-/); }
 finally { await rm(root, { recursive: true, force: true }); }
});
test('asset symlinks escaping the build are rejected', async () => {
 const { root, build } = await fixture();
 try { await writeFile(join(root, 'outside.js'), 'console.log("outside fixture");'); await rm(join(build, 'bundle.js')); await symlink(join(root, 'outside.js'), join(build, 'bundle.js')); assert.notEqual(run(build).status, 0); }
 finally { await rm(root, { recursive: true, force: true }); }
});
