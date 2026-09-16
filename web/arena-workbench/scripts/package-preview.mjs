#!/usr/bin/env node
/** Package the compiled React preview as one offline-openable HTML artifact. */
import { readFile, writeFile, realpath } from 'node:fs/promises';
import { resolve, dirname, relative, isAbsolute } from 'node:path';
import { createHash } from 'node:crypto';

const directory = await realpath(resolve(process.argv[2] ?? '/tmp/arena-ui-preview-dist'));
const input = resolve(directory, 'preview.html');
async function assetPath(url) {
 const path = resolve(dirname(input), url);
 const rel = relative(directory, path);
 if (isAbsolute(rel) || rel.startsWith('..')) throw Error('Preview asset escaped build directory');
 const resolved = await realpath(path);
 const resolvedRel = relative(directory, resolved);
 if (isAbsolute(resolvedRel) || resolvedRel.startsWith('..')) throw Error('Preview asset symlink escaped build directory');
 return resolved;
}
let html = await readFile(await assetPath('preview.html'), 'utf8');
const scripts = [...html.matchAll(/<script\b[^>]*src="([^"]+)"[^>]*><\/script>/g)];
const styles = [...html.matchAll(/<link\b[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>/g)];
if (scripts.length !== 1 || styles.length !== 1) throw Error('Expected one self-contained preview JS/CSS bundle');
const js = (await readFile(await assetPath(scripts[0][1]), 'utf8')).replace(/<\/script/gi, '<\\/script');
const css = (await readFile(await assetPath(styles[0][1]), 'utf8')).replace(/<\/style/gi, '<\\/style');
html = html.replace(scripts[0][0], () => `<script type="module">${js}</script>`);
html = html.replace(styles[0][0], () => `<style>${css}</style>`);
html = html.replace(/<link\b[^>]*rel="modulepreload"[^>]*>/g, '');
const scriptHash = createHash('sha256').update(js).digest('base64');
html = html.replace("script-src 'self'", `script-src 'sha256-${scriptHash}'`);
const output = resolve(directory, 'arena-workflow-preview.html');
await writeFile(output, html);
await writeFile(resolve(directory, 'package-proof.json'), JSON.stringify({
 artifact: 'arena-workflow-preview.html', sha256: createHash('sha256').update(html).digest('hex'),
 scriptHash, javascriptBundles: scripts.length, stylesheetBundles: styles.length,
 purpose: 'Design preview only. No API calls, credentials or research execution.',
}, null, 2));
console.log(output);
