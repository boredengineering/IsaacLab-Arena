# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Synthetic consistency fixtures only; never browser/API acceptance evidence."""
import copy
import json
import unittest
from urllib.parse import quote
import check_proof as checker


def fixture():
    sha = checker.sha
    api = {'view_id': 'a' * 32, 'source_hash': sha('loaded source')}
    original = 'position_xyz: [0.5, 0, 0] # preserve\n'
    values = [original, original.replace('0.5', '1.25'), original.replace('[0.5, 0, 0]', '[1.25, -0.25, 0]'), original.replace('[0.5, 0, 0]', '[1.25, -0.25, 0.125]')]
    proposals = [{'axis': axis, 'original': values[axis], 'candidate': values[axis + 1], 'canonical_hash': sha(values[axis + 1] + 'canonical')} for axis in range(3)]
    phases = [('raw-supported-table', original), ('invalid-raw', 'unknown_field: true\n'), ('recover-valid-raw', original), ('candidate-0', values[1]), ('candidate-0-after-aba', values[1]), ('fresh-applied-0', values[1]), ('candidate-1', values[2]), ('fresh-applied-1', values[2]), ('candidate-2', values[3]), ('fresh-applied-2', values[3])]
    validations, phase_records = [], []
    for index, (phase, yaml) in enumerate(phases, 1):
        request = {'yaml_text': yaml, 'document_id': api['view_id']}
        validations.append({'sequence': index, 'request': request, 'request_body': json.dumps(request), 'status': 200, 'response_request_sequence': index, 'response': {'valid': phase != 'invalid-raw', 'source_hash': sha(yaml), 'canonical_hash': sha(yaml + 'canonical')}})
        phase_records.append({'phase': phase, 'yaml': yaml, 'after_sequence': index - 1, 'request_sequence': index})
    request = {'idempotency_key': 'test-key', 'yaml_text': values[3], 'document_id': api['view_id'], 'expected_source_hash': api['source_hash']}
    rid = 'b' * 32
    revision = {'revision_id': rid, 'yaml_text': values[3], 'source_hash': sha(values[3]), 'canonical_hash': proposals[-1]['canonical_hash'], 'download_url': f'/api/editor/revisions/{rid}/download', 'open_source': {'kind': 'editor_revision', 'id': f'editor-revision:{rid}'}}
    receipt = {'schema_version': 1, 'state': 'committed', 'idempotency_key': request['idempotency_key'], 'request_sha256': sha(json.dumps(['editor-save/v1', request['yaml_text'], request['document_id'], request['expected_source_hash']], separators=(',', ':'), ensure_ascii=False)), 'revision': revision}
    source = revision['open_source']['id']
    row = {'id': source, 'kind': 'editor_revision', 'revision_id': rid, 'source_hash': revision['source_hash'], 'canonical_hash': revision['canonical_hash']}
    loaded = {'document_id': 'c' * 32, 'source': source, 'source_origin': revision['open_source'], 'yaml_text': values[3], 'source_hash': revision['source_hash'], 'validation': {'valid': True, 'source_hash': revision['source_hash'], 'canonical_hash': revision['canonical_hash']}}
    wire = [{'method': 'POST', 'path': '/api/editor/save', 'request': request, 'response': receipt}, {'method': 'GET', 'path': '/api/editor/save-requests/test-key', 'response': receipt}, {'method': 'GET', 'path': '/api/editor', 'response': {'documents': [row]}}, {'method': 'GET', 'path': '/api/editor/documents/' + quote(source, safe=''), 'response': loaded}, {'method': 'GET', 'path': '/api/editor/documents/' + quote(source, safe=''), 'response': loaded}]
    for index, value in enumerate(wire, 1): value.update(sequence=index, status=200, response_request_sequence=index)
    checks = ['candidate_transport_error_disables_apply', 'supported_table_actual_schema', 'invalid_schema_save_disabled', 'stale_option_aba_consent_retired', 'same_editor_through_apply', 'dirty_cancel_zero_document_reads', 'same_editor_navigation_prompt', 'save_does_not_open', 'library_exact_revision_before_open', 'explicit_open_same_editor', 'reload_exact_root_hash_origin_theme', 'zero_jobs', 'exact_blob_bytes', 'consent_and_fresh_validation_each_xyz']
    a = {'schema_version': 1, 'profile': 'authoring-v1', 'status': 'passed', 'remaining': [], 'checks': dict.fromkeys(checks, True), 'initial_draft': original, 'final_draft': values[3], 'final_sha256': sha(values[3]), 'proposals': proposals, 'phases': phase_records, 'exchanges': wire, 'save_sequence': 1, 'receipt_get_sequence': 2, 'library_index_sequence': 3, 'open_sequence': 4, 'reload_sequence': 5, 'geometry': [{'width': w, 'scrollWidth': w, 'theme': t, 'editorWidth': 300, 'background': 'rgb(0, 0, 0)' if t == 'dark' else 'rgb(255, 255, 255)'} for w in (1440, 390) for t in ('dark', 'light')], 'jobs': {'status': 200, 'body': {'jobs': []}}}
    final = {'profile': 'authoring-v1', 'allowed_authoring_writes': [{'method': 'POST', 'path': '/api/editor/save', 'request': request, 'status': 200}]}
    final["recreated_documents"] = [{"receipt": copy.deepcopy(receipt), "document": copy.deepcopy(loaded), "scope": "fresh Documents service over same private durable state; not API process restart"}]
    return a, validations, api, final


class AuthoringContractTests(unittest.TestCase):
    def test_positive_synthetic_contract(self):
        checker.authoring_contract(*fixture())

    def test_resealed_negative_correlations(self):
        mutations = [
            lambda a, v, api, f: a.update(status='failed'),
            lambda a, v, api, f: a.update(profile='readonly'),
            lambda a, v, api, f: a['checks'].update(zero_jobs=1),
            lambda a, v, api, f: a['phases'][5].update(request_sequence=4),
            lambda a, v, api, f: v[5].update(response_request_sequence=4),
            lambda a, v, api, f: v[5]['request'].update(document_id='d' * 32),
            lambda a, v, api, f: v[5]['request'].update(yaml_text='different bytes'),
            lambda a, v, api, f: v[5]['response'].update(source_hash='0' * 64),
            lambda a, v, api, f: a['proposals'][0].update(candidate='wrong numeric token'),
            lambda a, v, api, f: a['exchanges'][0]['request'].update(expected_source_hash='0' * 64),
            lambda a, v, api, f: a['exchanges'][1].update(response_request_sequence=1),
            lambda a, v, api, f: a['exchanges'][1]['response'].update(request_sha256='0' * 64),
            lambda a, v, api, f: a['exchanges'][2]['response']['documents'][0].update(canonical_hash='0' * 64),
            lambda a, v, api, f: a['exchanges'][3]['response'].update(source_origin={'kind': 'editor_revision', 'id': 'editor-revision:' + 'd' * 32}),
            lambda a, v, api, f: a['exchanges'][4]['response'].update(yaml_text='latest instead of exact'),
            lambda a, v, api, f: a['geometry'][2].update(scrollWidth=600),
            lambda a, v, api, f: f['recreated_documents'][0]['document'].update(source_hash='0' * 64),
            lambda a, v, api, f: f.update(allowed_authoring_writes=[]),
            lambda a, v, api, f: a['jobs']['body'].update(jobs=[{'id': 'unexpected'}]),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                data = copy.deepcopy(fixture())
                mutate(*data)
                with self.assertRaises((AssertionError, KeyError, ValueError)):
                    checker.authoring_contract(*data)


if __name__ == '__main__':
    unittest.main()
