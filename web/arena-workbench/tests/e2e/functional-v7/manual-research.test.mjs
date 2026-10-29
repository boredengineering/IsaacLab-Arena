// Copyright (c) 2026, The Isaac Lab Arena Project Developers.
// SPDX-License-Identifier: Apache-2.0
// Builtins-only synthetic requests; not browser/API results.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import * as manual from './browser-manual-research.mjs';

test('manual tracker requires the same request object and freezes wire bytes', async () => {
  assert.equal(typeof manual.createExchangeTracker, 'function');
  const tracker = manual.createExchangeTracker();
  let body = '{"family":"unit-only"}';
  const request = () => ({method: () => 'POST', url: () => 'http://127.0.0.1:31847/api/research/stores/manual-browser/versions', postData: () => body});
  const one = request(), other = request();
  tracker.request(one); body = '{"family":"changed"}';
  const response = r => ({request: () => r, status: () => 201, json: async () => ({unitOnly: true})});
  await tracker.response(response(other));
  assert.equal(tracker.records[0].response, undefined);
  await tracker.response(response(one));
  assert.equal(tracker.records[0].request.family, 'unit-only');
  assert.equal(tracker.records[0].response_request_sequence, 1);
});

test('delayed response cannot move to a newer same-path request', async () => {
  assert.equal(typeof manual.createExchangeTracker, 'function');
  const t = manual.createExchangeTracker();
  const request = () => ({method: () => 'GET', url: () => 'http://127.0.0.1:31847/api/editor', postData: () => null});
  const a = request(), b = request(); t.request(a); t.request(b);
  let finish;
  const pending = t.response({request: () => a, status: () => 200, json: () => new Promise(resolve => {finish = resolve;})});
  await t.response({request: () => b, status: () => 200, json: async () => ({unit: 'b'})});
  assert.equal(t.records[0].response, undefined);
  finish({unit: 'a'}); await pending;
  assert.equal(t.records[0].response.unit, 'a'); assert.equal(t.records[1].response.unit, 'b');
  assert.deepEqual(t.records.map(r => r.response_request_sequence), [1, 2]);
});
