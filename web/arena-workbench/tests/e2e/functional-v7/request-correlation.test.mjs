// Copyright (c) 2026, The Isaac Lab Arena Project Developers.
// SPDX-License-Identifier: Apache-2.0
// Pure node:test; importing browser.mjs must not preflight/build/start a browser.
import assert from 'node:assert/strict';
import test from 'node:test';
import { createValidationTracker } from './browser.mjs';

const request = (yaml = 'fixture\n', view = 'frozen') => ({
  url: () => 'http://127.0.0.1:31847/api/editor/validate', method: () => 'POST',
  postData: () => JSON.stringify({ yaml_text: yaml, document_id: view }),
});
const response = (req, body = { valid: true }, status = 200) => ({
  request: () => req, status: () => status, json: async () => body,
});

test('candidate validation cannot substitute for fresh Apply validation with identical YAML', async () => {
  const tracker = createValidationTracker();
  const candidate = request('position_xyz: [1.25, 0, 0]\n', 'source-view');
  tracker.request(candidate); await tracker.response(response(candidate, {valid: true, canonical_hash: 'same'}));
  const appliedBoundary = tracker.sequence;
  assert.equal(tracker.match(appliedBoundary, 'position_xyz: [1.25, 0, 0]\n', 'source-view'), undefined);
  const fresh = request('position_xyz: [1.25, 0, 0]\n', 'source-view');
  tracker.request(fresh);
  await tracker.response(response(candidate, {valid: true, canonical_hash: 'same'}));
  assert.equal(tracker.match(appliedBoundary, 'position_xyz: [1.25, 0, 0]\n', 'source-view'), undefined);
  await tracker.response(response(fresh, {valid: true, canonical_hash: 'same'}));
  assert.equal(tracker.match(appliedBoundary, 'position_xyz: [1.25, 0, 0]\n', 'source-view').sequence, 2);
});

test('same YAML validated under a recreated view cannot authorize the former frozen source', async () => {
  const tracker = createValidationTracker();
  const recreated = request('saved root\n', 'recreated-view');
  tracker.request(recreated); await tracker.response(response(recreated));
  assert.equal(tracker.match(0, 'saved root\n', 'original-view'), undefined);
  assert(tracker.match(0, 'saved root\n', 'recreated-view'));
});

test('suppressed edits/restores cannot borrow initial validation', async () => {
  const tracker = createValidationTracker();
  const initial = request(); tracker.request(initial); await tracker.response(response(initial));
  const after = tracker.sequence;
  assert.equal(tracker.match(after, 'fixture\n\n', 'frozen'), undefined);
  assert.equal(tracker.match(after, 'fixture\n', 'frozen'), undefined);
});

test('only the exact request object and frozen payload complete a phase', async () => {
  const tracker = createValidationTracker(), after = tracker.sequence;
  const req = request('edited\n'); tracker.request(req);
  await tracker.response(response(request('edited\n'))); // same bytes, different object
  assert.equal(tracker.match(after, 'edited\n', 'frozen'), undefined);
  await tracker.response(response(req));
  assert.equal(tracker.match(after, 'edited\n', 'other'), undefined);
  assert.equal(tracker.match(after, 'edited', 'frozen'), undefined);
  const found = tracker.match(after, 'edited\n', 'frozen');
  assert.equal(found.sequence, 1);
  assert.equal(found.request_body, req.postData());
  assert.equal(found.response_request_sequence, 1);
});

test('a delayed initial response cannot satisfy a later identical restore', async () => {
  const tracker = createValidationTracker();
  const initial = request(); tracker.request(initial);
  const edit = request('fixture\n\n'); const editAfter = tracker.sequence;
  tracker.request(edit); await tracker.response(response(edit));
  assert(tracker.match(editAfter, 'fixture\n\n', 'frozen'));
  const restoreAfter = tracker.sequence;
  await tracker.response(response(initial));
  assert.equal(tracker.match(restoreAfter, 'fixture\n', 'frozen'), undefined);
  const restore = request(); tracker.request(restore);
  assert.equal(tracker.match(restoreAfter, 'fixture\n', 'frozen'), undefined); // response suppressed
  await tracker.response(response(restore));
  assert(tracker.match(restoreAfter, 'fixture\n', 'frozen'));
});

test('reordered asynchronous response bodies remain paired with request sequences', async () => {
  const tracker = createValidationTracker();
  const edited = request('edited\n'), restored = request();
  tracker.request(edited); tracker.request(restored);
  let resolve;
  const delayed = tracker.response({ ...response(edited), json: () => new Promise(done => { resolve = done; }) });
  await tracker.response(response(restored, { marker: 'restore' }));
  resolve({ marker: 'edit' }); await delayed;
  assert.equal(tracker.match(0, 'edited\n', 'frozen').response.marker, 'edit');
  assert.equal(tracker.match(1, 'fixture\n', 'frozen').response.marker, 'restore');
});

test('reordered requests cannot move an early restore across its edit boundary', async () => {
  const tracker = createValidationTracker();
  const earlyRestore = request(), edit = request('edited\n');
  tracker.request(earlyRestore); // a restore-like request dispatched before the edit
  const editAfter = tracker.sequence;
  tracker.request(edit); await tracker.response(response(edit));
  assert(tracker.match(editAfter, 'edited\n', 'frozen'));
  const restoreAfter = tracker.sequence;
  await tracker.response(response(earlyRestore));
  assert.equal(tracker.match(restoreAfter, 'fixture\n', 'frozen'), undefined);
  const delayedRestore = request();
  await tracker.response(response(delayedRestore)); // response without an observed request is not adopted
  tracker.request(delayedRestore);
  assert.equal(tracker.match(restoreAfter, 'fixture\n', 'frozen'), undefined);
  await tracker.response(response(delayedRestore));
  assert(tracker.match(restoreAfter, 'fixture\n', 'frozen'));
});

test('capture immutable payload at request time; wrong-method and failed responses do not match', async () => {
  const tracker = createValidationTracker();
  const req = request('edited\n'); tracker.request(req);
  req.postData = () => JSON.stringify({ yaml_text: 'changed', document_id: 'other' });
  await tracker.response(response(req));
  assert.equal(tracker.match(0, 'edited\n', 'frozen').request.yaml_text, 'edited\n');
  const bad = request(); tracker.request(bad); await tracker.response(response(bad, {}, 500));
  assert.equal(tracker.match(0, 'fixture\n', 'frozen'), undefined);
  const get = { ...request(), method: () => 'GET' }; tracker.request(get);
  assert.equal(tracker.sequence, 2);
});
