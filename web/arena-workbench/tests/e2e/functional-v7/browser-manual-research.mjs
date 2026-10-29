// Copyright (c) 2026, The Isaac Lab Arena Project Developers.
// SPDX-License-Identifier: Apache-2.0
// Genuine production UI only. Importing this file never starts a browser/build.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

export function createExchangeTracker() {
  const records = [], byRequest = new WeakMap();
  return {records, get sequence() { return records.length; },
    request(request) {
      const url = new URL(request.url());
      if (!(url.pathname === '/api/editor' || url.pathname.startsWith('/api/editor/') ||
            url.pathname.startsWith('/api/research/') || ['/api/jobs', '/api/health'].includes(url.pathname))) return;
      assert(records.length < 2000, 'Bounded manual request budget');
      const row = {sequence: records.length + 1, method: request.method(), path: url.pathname, target: url.pathname + url.search};
      const raw = request.postData();
      if (raw !== null) { row.request_body = raw; row.request = JSON.parse(raw); }
      byRequest.set(request, row); records.push(row);
    },
    async response(response) {
      const row = byRequest.get(response.request()); if (!row) return;
      row.status = response.status();
      try { row.response = await response.json(); row.response_request_sequence = row.sequence; }
      catch (error) { row.error = String(error); }
    },
  };
}

export async function manualResearch({page, proof, api, expect, out, sha256, tracker}) {
  const a = proof.manual_research = {schema_version: 1, profile: 'manual-research-v1', status: 'failed',
    remaining: [], exchanges: tracker.records, versions: [], screenshots: [],
    limitations: ['No provider/graph/render/physics execution', 'Reload is not API process restart']};
  const content = page.locator('.cm-content');
  const button = name => page.getByRole('button', {name, exact: true});
  const path = '/api/research/stores/manual-browser/versions';
  const find = (after, method, path) => tracker.records.find(r => r.sequence > after && r.method === method && decodeURIComponent(r.path) === path && r.response_request_sequence === r.sequence && r.response);
  async function row(after, method, path, status = 200) {
    await expect.poll(() => !!find(after, method, path), {timeout: 15000}).toBe(true);
    const r = find(after, method, path); assert.equal(r.status, status); return r;
  }
  async function bytes() {
    await page.evaluate(() => navigator.clipboard.writeText('manual: no editor bytes copied'));
    await content.click(); await page.keyboard.press('Control+a'); await page.keyboard.press('Control+c');
    const text = await page.evaluate(() => navigator.clipboard.readText());
    await page.keyboard.press('ArrowRight'); return text;
  }
  async function shot(name) { await page.screenshot({path: `${out}/${name}.png`, fullPage: true}); a.screenshots.push(`${name}.png`); }
  async function validated(text, view, action) {
    const before = tracker.sequence; await action();
    const match = () => tracker.records.find(r => r.sequence > before && r.path === '/api/editor/validate' &&
      r.method === 'POST' && r.request?.yaml_text === text && r.request?.document_id === view &&
      r.response_request_sequence === r.sequence && r.status === 200 && r.response);
    await expect.poll(() => !!match(), {timeout: 15000}).toBe(true);
    const r = match(); assert.equal(r.response.valid, true); assert.equal(r.response.source_hash, sha256(text)); return r;
  }
  const initialIndex = await row(0, 'GET', '/api/editor'); a.index = initialIndex.sequence;
  a.health = (await row(0, 'GET', '/api/health')).sequence;
  for (const name of ['durable_editor_save', 'research_versions', 'manual_research_save', 'research_version_open']) assert.equal(initialIndex.response.capabilities[name], true);
  for (const name of ['generation', 'snapshots', 'neo4j', 'publication_execution']) assert.equal(initialIndex.response.capabilities[name], false);
  assert.deepEqual(initialIndex.response.capabilities, api.capabilities);
  await expect(page.getByRole('checkbox', {name: 'Automatic previews (GPU jobs)', exact: true})).not.toBeChecked();
  a.automatic_previews = false;
  const draft = '# Manual browser research: exact raw root\n' + api.yaml_text;
  a.draft = draft; a.draft_sha256 = sha256(draft);
  a.validation = (await validated(draft, api.view_id, () => content.fill(draft))).sequence;
  await expect(button('Save durable revision')).toBeEnabled();
  const beforeSave = tracker.sequence;
  await button('Save durable revision').click();
  const save = await row(beforeSave, 'POST', '/api/editor/save'); a.save = save.sequence;
  const receipt = await row(save.sequence, 'GET', '/api/editor/save-requests/' + save.request.idempotency_key);
  assert.deepEqual(receipt.response, save.response); a.save_get = receipt.sequence;
  await expect(button('Open saved revision')).toBeEnabled();
  assert.equal(await bytes(), draft);
  await button('Open research versions').click();
  await page.getByRole('combobox', {name: /^Research save source/}).selectOption('manual');
  await expect(page.getByRole('combobox', {name: /^Research save source/})).toHaveValue('manual');
  const stores = await row(0, 'GET', '/api/research/stores'); a.stores = stores.sequence;
  assert.equal(stores.response.stores.length, 1); assert.equal(stores.response.stores[0].available, true);
  await page.getByRole('combobox', {name: /^Research store/}).selectOption('manual-browser');
  await page.getByLabel('Research family', {exact: true}).fill('browser-family');
  a.no_parent = {before: tracker.sequence};
  await expect(button('Save numbered research version')).toBeDisabled();
  await expect(page.getByRole('combobox', {name: /^Parent revision/})).toHaveValue('');
  a.no_parent.after = tracker.sequence; a.no_parent.save_disabled = true;
  await page.getByRole('combobox', {name: /^Parent revision/}).selectOption('none');
  let selected;
  for (const number of [1, 2]) {
    const parent_selection = number === 1 ? null : selected.sequence;
    if (number === 2) await page.getByRole('combobox', {name: /^Parent revision/}).selectOption(selected.response.reservation.revision_id);
    const parent_choice = await page.getByRole('combobox', {name: /^Parent revision/}).inputValue();
    await expect(button('Save numbered research version')).toBeEnabled();
    const before = tracker.sequence;
    const dialog = page.waitForEvent('dialog');
    const click = button('Save numbered research version').click();
    const confirmation = await dialog;
    assert.match(confirmation.message(), /Save numbered research version/);
    assert.match(confirmation.message(), /Manual graph publication is unsupported/);
    await confirmation.accept(); await click;
    const post = await row(before, 'POST', path, 201);
    const r = post.response.reservation;
    assert.equal(r.version, number); assert.equal(post.response.publication_intent_id, null);
    const get = await row(post.sequence, 'GET', `${path}/${r.reservation_id}`);
    assert.deepEqual(get.response, post.response);
    a.versions.push({before, post: post.sequence, get: get.sequence, parent_selection, parent_choice});
    await expect(page.getByText('Research version saved and verified. Graph publication was not performed.', {exact: true})).toBeVisible();
    const selectBoundary = tracker.sequence;
    await button(`Select version ${number}`).click();
    selected = await row(selectBoundary, 'GET', `${path}/${r.reservation_id}`);
    await expect(button('Open research version in editor')).toBeVisible();
    assert.equal(await bytes(), draft);
  }
  a.selected_get = selected.sequence;
  a.no_auto_open = {before: a.save, after: a.selected_get, yaml: await bytes()};
  assert(!tracker.records.slice(a.save, a.selected_get).some(r => r.path.startsWith('/api/editor/documents/')));
  const r = selected.response.reservation, manifest = selected.response.manifest;
  const identity = {store_id:r.store_id, reservation_id:r.reservation_id, revision_id:r.revision_id,
    family:r.family, version:r.version, manifest_digest:manifest.digest, source:r.source};
  const descriptor = `research-version:${r.store_id}:${r.reservation_id}:${manifest.digest}`;
  const docPath = '/api/editor/documents/' + descriptor;
  await shot('manual-research-saved');
  const dirty = draft + '# Cancel must retain this dirty draft\n';
  await validated(dirty, api.view_id, () => content.fill(dirty));
  a.cancel = {before: tracker.sequence, yaml_before: await bytes()};
  const cancelDialog = page.waitForEvent('dialog'); const cancelClick = button('Open research version in editor').click();
  const cancellation = await cancelDialog; await cancellation.dismiss(); await cancelClick;
  // Observe a bounded quiet interval after the synchronous dirty-confirmation cancellation.
  await page.waitForTimeout(300);
  Object.assign(a.cancel, {after: tracker.sequence, yaml_after: await bytes(), dialog: 'dismissed'});
  assert.equal(a.cancel.yaml_after, dirty);
  assert(!tracker.records.slice(a.cancel.before, a.cancel.after).some(r => r.path.startsWith('/api/editor/documents/')));
  const openBoundary = tracker.sequence;
  const openDialog = page.waitForEvent('dialog'); const openClick = button('Open research version in editor').click();
  await (await openDialog).accept(); await openClick;
  const opened = await row(openBoundary, 'GET', docPath); a.open = opened.sequence;
  async function exact(doc) {
    assert.deepEqual(doc.research_identity, identity);
    assert.deepEqual(doc.source_origin, {kind:'research_version', id:descriptor});
    assert.equal(doc.yaml_text, draft); assert.equal(doc.source_hash, sha256(draft));
    assert.equal(doc.validation.canonical_hash, save.response.revision.canonical_hash);
    await expect(page.getByLabel('Document', {exact:true})).toHaveValue(descriptor);
    await expect(content).toBeVisible(); assert.equal(await bytes(), draft);
  }
  await exact(opened.response); a.open_yaml = await bytes();
  const downloadEvent = page.waitForEvent('download'); await button('Download current YAML').click();
  const download = await downloadEvent; assert(download.url().startsWith('blob:'));
  await download.saveAs(`${out}/manual-research-root.yaml`);
  const raw = await readFile(`${out}/manual-research-root.yaml`); assert.deepEqual(raw, Buffer.from(draft));
  a.download = {artifact:'manual-research-root.yaml', bytes:raw.length, sha256:sha256(raw), url_scheme:'blob:'};
  await shot('manual-research-opened');
  // Selection recovery is carried by a genuine production backup, not a hint
  // injected by the harness. Keep root bytes unchanged but retain a user prompt.
  const prompt = 'Retain this explicit manual research context';
  await page.getByLabel('Describe the environment and task', {exact:true}).fill(prompt);
  const backup = () => page.evaluate(() => {
    const raw = sessionStorage.getItem('arena.editor.draft.v1'); return raw ? JSON.parse(raw) : null;
  });
  await expect.poll(async () => (await backup())?.prompt).toBe(prompt);
  a.reload_context = {prompt, backup: await backup()};
  let before = tracker.sequence; await page.reload();
  const reload = await row(before, 'GET', docPath); a.reload = reload.sequence;
  await exact(reload.response); assert.notEqual(reload.response.document_id, opened.response.document_id);
  a.reload_yaml = await bytes();
  a.reload_context.root = await bytes();
  await expect(button('Restore draft')).toBeEnabled();
  await button('Restore draft').click();
  await expect(page.getByLabel('Describe the environment and task', {exact:true})).toHaveValue(prompt);
  a.reload_context.explicit = true;
  const recovered = draft + '# Explicit research recovery only\n';
  await validated(recovered, reload.response.document_id, () => content.fill(recovered));
  a.recovery = {draft:recovered, draft_before_reload:await bytes()};
  // Wait for the production backup, never write or repair its persisted record.
  await expect.poll(async () => (await backup())?.draft).toBe(recovered);
  a.recovery.backup = await backup();
  before = tracker.sequence; await page.reload();
  const recoveryLoad = await row(before, 'GET', docPath); a.recovery_load = recoveryLoad.sequence;
  await exact(recoveryLoad.response);
  assert.notEqual(recoveryLoad.response.document_id, reload.response.document_id);
  await expect(button('Restore draft')).toBeEnabled();
  a.recovery.root_before_restore = await bytes(); a.recovery.before = tracker.sequence;
  const restored = await validated(recovered, recoveryLoad.response.document_id, () => button('Restore draft').click());
  a.recovery.validation = restored.sequence; a.recovery.explicit = true; a.recovery.restored = await bytes();
  assert.equal(a.recovery.restored, recovered);
  await shot('manual-research-recovered');
  // Independent read-only observation, never a substitute for a UI mutation/Open.
  before = tracker.sequence;
  await page.evaluate(async () => { const response = await fetch('/api/jobs'); await response.json(); });
  const jobs = await row(before, 'GET', '/api/jobs'); a.jobs = jobs.sequence;
  assert.deepEqual(jobs.response.jobs, []);
  assert.equal(tracker.records.filter(r => r.method === 'POST' && r.path === '/api/editor/save').length, 1);
  assert.equal(tracker.records.filter(r => r.method === 'POST' && r.path === path).length, 2);
  await expect(page.getByRole('checkbox', {name:'Automatic previews (GPU jobs)', exact:true})).not.toBeChecked();
  a.status = 'passed';
}
