// Copyright (c) 2026, The Isaac Lab Arena Project Developers.
// SPDX-License-Identifier: Apache-2.0
// Genuine production UI driver: no response fulfillment or editor substitution.
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';

export async function authoring({page, context, proof, api, validations, expect, out, sha256}) {
  const a = proof.authoring = {schema_version: 1, profile: 'authoring-v1', status: 'failed',
    phases: [], exchanges: [], checks: {}, geometry: [], screenshots: [], remaining: [],
    limitations: ['No GPU/physics/F4 renderer acceptance', 'Browser reload is not API process restart']};
  a.health = await page.evaluate(async () => {const r = await fetch('/api/health'); return {status:r.status, body:await r.json()};});
  const byRequest = new WeakMap();
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (!(path === '/api/editor' || path.startsWith('/api/editor/') || path === '/api/jobs' || path === '/api/health')) return;
    const row = {sequence: a.exchanges.length + 1, method: request.method(), path};
    if (request.postData()) row.request = JSON.parse(request.postData());
    byRequest.set(request, row); a.exchanges.push(row);
  });
  page.on('response', async response => {
    const row = byRequest.get(response.request());
    if (!row) return;
    row.status = response.status();
    try { row.response = await response.json(); row.response_request_sequence = row.sequence; } catch {}
  });
  const content = page.locator('.cm-content');
  const originalEditor = await content.elementHandle();
  async function sameEditor() { assert(await content.evaluate((node, original) => node === original, originalEditor)); }
  async function editorBytes() {
    await page.evaluate(() => navigator.clipboard.writeText('authoring: not copied'));
    await content.click(); await page.keyboard.press('Control+a'); await page.keyboard.press('Control+c');
    const text = await page.evaluate(() => navigator.clipboard.readText());
    await page.keyboard.press('ArrowRight'); return text;
  }
  async function validation(phase, yaml, action, valid = true) {
    const after_sequence = validations.sequence;
    await action();
    await expect.poll(() => !!validations.match(after_sequence, yaml, api.view_id), {timeout: 15000}).toBe(true);
    const row = validations.match(after_sequence, yaml, api.view_id);
    assert.equal(row.response.valid, valid); assert.equal(row.response.source_hash, sha256(yaml));
    a.phases.push({phase, yaml, after_sequence, request_sequence: row.sequence});
    return row;
  }
  async function screenshot(name) {
    await page.screenshot({path: `${out}/${name}.png`, fullPage: true}); a.screenshots.push(`${name}.png`);
  }
  const saves = () => a.exchanges.filter(r => r.method === 'POST' && r.path === '/api/editor/save');
  const documentReads = () => a.exchanges.filter(r => r.path.startsWith('/api/editor/documents/')).length;
  async function blobDownload(name, yaml) {
    const waiting = page.waitForEvent('download');
    await page.getByRole('button', {name: 'Download current YAML', exact: true}).click();
    const download = await waiting;
    assert(download.url().startsWith('blob:'));
    await download.saveAs(`${out}/${name}.yaml`);
    const bytes = await readFile(`${out}/${name}.yaml`);
    assert.deepEqual(bytes, Buffer.from(yaml));
    return {artifact: `${name}.yaml`, url_scheme: 'blob:', suggested_filename: download.suggestedFilename(), bytes: bytes.length, sha256: sha256(bytes)};
  }
  // Keep the actual loaded embodiment section. Deliberately remove incident refs,
  // constraints and tasks; use the inspector's narrow real background/table schema.
  const embodiment = api.yaml_text.match(/embodiment:\n[\s\S]*?(?=background:\n)/)?.[0];
  assert(embodiment?.includes('droid_abs_joint_pos'));
  let draft = '# Browser-authored supported table; retained raw comment\nenv_name: browser_authored_table\n' + embodiment +
    'background:\n  id: desk\n  registry_name: table\n  params:\n    initial_pose:\n      position_xyz: [0.5, 0, 0] # meters; preserve this comment\n      rotation_xyzw: [0, 0, 0, 1]\nobjects: []\nrelations: []\ntask: {composition: atomic, subtasks: [{kind: NoTask, params: {}}]}\n';
  a.initial_draft = draft;
  await validation('raw-supported-table', draft, () => content.fill(draft));
  await expect(page.getByRole('button', {name: /^Save (durable )?revision$/})).toBeEnabled();
  await page.getByLabel('Authored asset', {exact: true}).selectOption('desk');
  await expect(page.getByLabel('Proposed coordinate (m)', {exact: true})).toBeVisible();
  await expect(page.getByRole('checkbox', {name: 'Automatic previews (GPU jobs)', exact: true})).not.toBeChecked();
  a.checks.supported_table_actual_schema = true;
  a.download_before_apply = await blobDownload('authoring-raw-download', draft);

  // UI error state from a genuine invalid schema response, not synthetic wire data.
  await validation('invalid-raw', 'unknown_field: true\n', () => content.fill('unknown_field: true\n'), false);
  await expect(page.getByRole('button', {name: /^Save (durable )?revision$/})).toBeDisabled();
  await validation('recover-valid-raw', draft, () => content.fill(draft));
  await page.getByLabel('Authored asset', {exact: true}).selectOption('desk');
  a.checks.invalid_schema_save_disabled = true;
  a.proposals = [];
  for (const [axis, before, value] of [[0, '0.5', '1.25'], [1, '0', '-0.25'], [2, '0', '0.125']]) {
    await expect(page.getByRole('button', {name: /^Save (durable )?revision$/})).toBeEnabled();
    await page.getByLabel('Authored asset', {exact: true}).selectOption('desk');
    await page.getByLabel('Position axis', {exact: true}).selectOption(String(axis));
    await page.getByLabel('Proposed coordinate (m)', {exact: true}).fill(value);
    if (axis === 0) {
      const abort = route => route.abort('failed');
      await page.route('**/api/editor/validate', abort);
      await page.getByRole('button', {name: 'Validate position proposal', exact: true}).click();
      await expect(page.getByText('Candidate validation failed', {exact: true})).toBeVisible();
      await expect(page.getByRole('button', {name: 'Apply reviewed position', exact: true})).toBeDisabled();
      assert.equal(await editorBytes(), draft);
      await page.unroute('**/api/editor/validate', abort);
      a.checks.candidate_transport_error_disables_apply = true;
    }
    const positions = draft.match(/position_xyz: \[([^\]]+)\]/)[1].split(', ');
    assert.equal(positions[axis], before); positions[axis] = value;
    const candidate = draft.replace(/position_xyz: \[[^\]]+\]/, `position_xyz: [${positions.join(', ')}]`);
    await validation(`candidate-${axis}`, candidate, () => page.getByRole('button', {name: 'Validate position proposal', exact: true}).click());
    await expect(page.getByRole('checkbox', {name: 'I reviewed this exact source diff', exact: true})).toBeEnabled();
    assert.equal(await editorBytes(), draft);
    await expect(page.getByRole('button', {name: 'Apply reviewed position', exact: true})).toBeDisabled();
    await page.getByRole('checkbox', {name: 'I reviewed this exact source diff', exact: true}).check();
    if (axis === 0) {
      // A→B→A option identity must not revive prior diff consent.
      await page.getByLabel('Proposed coordinate (m)', {exact: true}).fill('9');
      await page.getByLabel('Proposed coordinate (m)', {exact: true}).fill(value);
      await expect(page.getByRole('button', {name: 'Apply reviewed position', exact: true})).toHaveCount(0);
      assert.equal(await editorBytes(), draft);
      await validation('candidate-0-after-aba', candidate, () => page.getByRole('button', {name: 'Validate position proposal', exact: true}).click());
      await expect(page.getByRole('checkbox', {name: 'I reviewed this exact source diff', exact: true})).toBeEnabled();
      await expect(page.getByRole('checkbox', {name: 'I reviewed this exact source diff', exact: true})).not.toBeChecked();
      await page.getByRole('checkbox', {name: 'I reviewed this exact source diff', exact: true}).check();
      a.checks.stale_option_aba_consent_retired = true;
      await screenshot('authoring-reviewed-diff');
    }
    const applied = await validation(`fresh-applied-${axis}`, candidate, async () => {
      await page.getByRole('button', {name: 'Apply reviewed position', exact: true}).click();
      await expect(page.getByRole('button', {name: /^Save (durable )?revision$/})).toBeDisabled();
    });
    assert.equal(await editorBytes(), candidate);
    a.proposals.push({axis, original: draft, candidate, canonical_hash: applied.response.canonical_hash});
    draft = candidate; await sameEditor();
  }
  a.final_draft = draft; a.final_sha256 = sha256(draft);
  a.download_after_apply = await blobDownload('authoring-final-download', draft);
  a.checks.exact_blob_bytes = true;
  a.checks.consent_and_fresh_validation_each_xyz = true;
  a.checks.same_editor_through_apply = true;

  // Dirty cancel must not perform document I/O or replace bytes.
  await page.getByLabel('Describe the environment and task', {exact: true}).fill('Retain this authoring prompt');
  await page.getByRole('link', {name: 'Library', exact: true}).click();
  await page.getByRole('button', {name: 'Inspect pick_and_place_maple_table_env_graph', exact: true}).click();
  const beforeCancel = documentReads();
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', {name: 'Open source in editor', exact: true}).click();
  await page.getByRole('link', {name: 'Environment editor', exact: true}).click();
  await expect(content).toBeVisible(); await sameEditor();
  assert.equal(documentReads(), beforeCancel); assert.equal(await editorBytes(), draft);
  await expect(page.getByLabel('Describe the environment and task', {exact: true})).toHaveValue('Retain this authoring prompt');
  a.checks.dirty_cancel_zero_document_reads = true;
  a.checks.same_editor_navigation_prompt = true;

  await expect(page.getByRole('button', {name: /^Save (durable )?revision$/})).toBeEnabled();
  if (!await page.getByRole('button', {name: 'Save durable revision', exact: true}).count()) {
    for (const width of [1440, 390]) {
      await page.setViewportSize({width, height: width === 390 ? 844 : 1100});
      for (const theme of ['dark', 'light']) {
        const toggle = page.getByRole('switch', {name: 'Dark mode', exact: true});
        if ((await toggle.getAttribute('aria-checked') === 'true') !== (theme === 'dark')) await toggle.click();
        await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
        await sameEditor(); assert.equal(await editorBytes(), draft);
        const geometry = await page.evaluate(() => ({width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
          theme: document.documentElement.dataset.theme, background: getComputedStyle(document.body).backgroundColor,
          editorWidth: document.querySelector('.cm-editor').getBoundingClientRect().width,
          overflow: [...document.querySelectorAll('body *')].map(e => ({tag:e.tagName, cls:e.className?.toString(), right:e.getBoundingClientRect().right, width:e.getBoundingClientRect().width})).filter(e => e.width > 0 && e.right > innerWidth + 1).slice(0, 24)}));
        a.geometry.push(geometry);
        await screenshot(`authoring-${width}-${theme}`);
        if (geometry.scrollWidth > width + 1) a.remaining.push(`horizontal overflow ${width}/${theme}: ${geometry.scrollWidth}`);
      }
    }
    a.remaining.push('Durable Save POST+GET, Library exact revision, explicit reopen and reload blocked: health capability absent');
    a.jobs = await page.evaluate(async () => {const r = await fetch('/api/jobs'); return {status:r.status, body:await r.json()};});
    assert.deepEqual(a.jobs.body.jobs, []);
    a.checks.zero_jobs = true;
    await screenshot('authoring-durable-capability-blocked');
    throw Error(a.remaining.join('; '));
  }
  a.before_save_document_reads = documentReads();
  await page.getByRole('button', {name: /^Save (durable )?revision$/}).click();
  await expect(page.getByRole('button', {name: 'Open saved revision', exact: true})).toBeEnabled({timeout: 15000});
  await expect.poll(() => saves().length).toBe(1);
  const saved = saves()[0];
  await expect.poll(() => !!saved.response).toBe(true);
  a.save_sequence = saved.sequence;
  const request = saved.request, receipt = saved.response, revision = receipt.revision;
  assert.equal(request.yaml_text, draft); assert.equal(request.document_id, api.view_id);
  assert.equal(request.expected_source_hash, api.source_hash);
  assert.equal(receipt.state, 'committed'); assert.equal(revision.yaml_text, draft);
  assert.equal(revision.source_hash, sha256(draft));
  const get = a.exchanges.find(r => r.method === 'GET' && r.path === `/api/editor/save-requests/${request.idempotency_key}`);
  await expect.poll(() => !!get?.response).toBe(true);
  assert.deepEqual(get.response, receipt); a.receipt_get_sequence = get.sequence;
  assert.equal(documentReads(), a.before_save_document_reads);
  await expect(page.getByLabel('Document', {exact: true})).toHaveValue(api.source_id);
  assert.equal(await editorBytes(), draft); a.checks.save_does_not_open = true;
  const revisionSource = revision.open_source.id;
  await page.getByRole('link', {name: 'Library', exact: true}).click();
  await page.getByRole('button', {name: `Inspect Editor revision ${revision.revision_id}`, exact: true}).click();
  await expect(page.getByRole('region', {name: 'Source inspection', exact: true})).toContainText(revision.source_hash);
  await expect(page.getByRole('button', {name: 'Pin exact revision', exact: true})).toBeDisabled();
  const index = a.exchanges.filter(r => r.method === 'GET' && r.path === '/api/editor' && r.response?.documents?.some(d => d.id === revisionSource)).at(-1);
  assert(index); a.library_index_sequence = index.sequence;
  a.checks.library_exact_revision_before_open = true;
  await screenshot('authoring-library-before-open');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', {name: 'Open source in editor', exact: true}).click();
  await expect(page.getByLabel('Document', {exact: true})).toHaveValue(revisionSource);
  assert.equal(await editorBytes(), draft); await sameEditor();
  const opened = a.exchanges.filter(r => r.method === 'GET' && decodeURIComponent(r.path) === `/api/editor/documents/${revisionSource}`).at(-1);
  await expect.poll(() => !!opened?.response).toBe(true);
  a.open_sequence = opened.sequence;
  assert.equal(opened.response.yaml_text, draft); assert.equal(opened.response.source_hash, sha256(draft));
  assert.deepEqual(opened.response.source_origin, revision.open_source);
  a.checks.explicit_open_same_editor = true;

  // Actual download endpoint is flattened export; local Blob remains exact root.
  a.revision_download = await page.evaluate(async url => {
    const r = await fetch(url); return {status: r.status, text: await r.text()};
  }, revision.download_url);
  assert.equal(a.revision_download.status, 200);
  await writeFile(`${out}/authoring-revision-export.yaml`, a.revision_download.text);
  a.revision_download.sha256 = sha256(a.revision_download.text);

  // CSS geometry is observed independently at both widths/themes, not inferred.
  for (const [width, height] of [[1440, 1100], [390, 844]]) {
    await page.setViewportSize({width, height});
    for (const theme of ['dark', 'light']) {
      const toggle = page.getByRole('switch', {name: 'Dark mode', exact: true});
      if ((await toggle.getAttribute('aria-checked') === 'true') !== (theme === 'dark')) {
        await toggle.focus(); await page.keyboard.press('Space');
      }
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await sameEditor(); assert.equal(await editorBytes(), draft);
      const geometry = await page.evaluate(() => ({width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
        theme: document.documentElement.dataset.theme, background: getComputedStyle(document.body).backgroundColor,
        editorWidth: document.querySelector('.cm-editor').getBoundingClientRect().width,
          overflow: [...document.querySelectorAll('body *')].map(e => ({tag:e.tagName, cls:e.className?.toString(), right:e.getBoundingClientRect().right, width:e.getBoundingClientRect().width})).filter(e => e.width > 0 && e.right > innerWidth + 1).slice(0, 24)}));
      a.geometry.push(geometry);
      await screenshot(`authoring-${width}-${theme}`);
      if (geometry.scrollWidth > width + 1) a.remaining.push(`horizontal overflow ${width}/${theme}: ${geometry.scrollWidth}`);
    }
  }
  await page.setViewportSize({width: 1440, height: 1100});
  const toggle = page.getByRole('switch', {name: 'Dark mode', exact: true});
  if (await toggle.getAttribute('aria-checked') !== 'true') await toggle.click();
  const reloadBoundary = a.exchanges.length;
  await page.reload();
  await expect(content).toBeVisible({timeout: 15000});
  await expect(page.getByLabel('Document', {exact: true})).toHaveValue(revisionSource);
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  assert.equal(await editorBytes(), draft);
  const reloaded = a.exchanges.find(r => r.sequence > reloadBoundary && r.method === 'GET' && decodeURIComponent(r.path) === `/api/editor/documents/${revisionSource}`);
  await expect.poll(() => !!reloaded?.response).toBe(true);
  const withoutView = ({document_id, ...document}) => document;
  assert.match(reloaded.response.document_id, /^[a-f0-9]{32}$/);
  assert.deepEqual(withoutView(reloaded.response), withoutView(opened.response));
  a.reload_sequence = reloaded.sequence;
  a.checks.reload_exact_root_hash_origin_theme = true;
  await screenshot('authoring-reloaded');
  a.jobs = await page.evaluate(async () => { const r = await fetch('/api/jobs'); return {status: r.status, body: await r.json()}; });
  assert.equal(a.jobs.status, 200); assert.deepEqual(a.jobs.body.jobs, []);
  assert.equal(saves().length, 1);
  a.checks.zero_jobs = true;
  a.checks.exact_blob_bytes = true;
  a.checks.consent_and_fresh_validation_each_xyz = true;
  assert.deepEqual(a.remaining, [], 'Authoring journeys remain failed');
  a.status = 'passed';
}
