# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Synthetic harness contracts only; never API responses or browser evidence."""
import copy
import unittest
import api

PROFILE = 'manual-research-v1'
PATH = '/api/research/stores/manual-browser/versions'


def payload():
    return {'idempotency_key': 'manual-test', 'family': 'browser-family', 'parent_revision_id': None,
            'source': {'kind': 'editor_revision', 'editor_revision_id': 'a' * 32,
                       'source_hash': 'b' * 64, 'canonical_hash': 'c' * 64}}


class ManualFirewallTests(unittest.TestCase):
    def boundary(self, raw, path=PATH, profile=PROFILE, chunks=None):
        """Execute the actual nested shim middleware without importing the API."""
        import ast
        import asyncio
        import json
        from pathlib import Path
        from types import SimpleNamespace
        import manual_research as m
        tree = ast.parse(Path(api.__file__).read_text())
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'workload_boundary')
        node.decorator_list = []
        counts = {'workload': 0}; budget = m.MutationBudget(); writes = []; handled = []
        async def json_body(): return json.loads(raw)
        async def stream():
            for chunk in (chunks if chunks is not None else [raw]): yield chunk
        request = SimpleNamespace(method='POST', url=SimpleNamespace(path=path.split('?')[0], query=path.partition('?')[2]),
                                  json=json_body, stream=stream)
        async def handler(request):
            handled.append(request)
            return SimpleNamespace(status_code=201)
        namespace = dict(vars(api), manual=profile == PROFILE, profile_name=profile, counters=counts,
                         manual_budget=budget, authoring_writes=writes, manual_writes=writes,
                         JSONResponse=lambda body, status_code: SimpleNamespace(status_code=status_code))
        exec(compile(ast.Module(body=[node], type_ignores=[]), api.__file__, 'exec'), namespace)
        response = asyncio.run(namespace['workload_boundary'](request, handler))
        return response.status_code, budget.remaining, handled, writes, counts

    def test_duplicate_raw_keys_rejected_before_budget_or_handler(self):
        import json
        from manual_research import MutationBudget
        version = json.dumps(payload()).encode()
        editor = json.dumps({'idempotency_key': 'browser-key', 'yaml_text': 'inert: true\n',
                             'document_id': 'a'*32, 'expected_source_hash': 'b'*64}).encode()
        cases = [(PATH, version.replace(b'{', b'{"family":"other",', 1)),
                 (PATH, version.replace(b'"kind":', b'"kind":"accepted_candidate","kind":', 1)),
                 (PATH, version.replace(b'"kind":', b'"k\\u0069nd":"editor_revision","kind":', 1)),
                 ('/api/editor/save', editor.replace(b'{', b'{"yaml_text":"old",', 1)),
                 (PATH, version.replace(b'"family":', b'"family":"browser-family","family":', 1))]
        for path, raw in cases:
            status, remaining, handled, writes, counts = self.boundary(raw, path)
            with self.subTest(path=path, raw=raw):
                self.assertEqual(status, 403)
                self.assertEqual(remaining, MutationBudget().remaining)
                self.assertEqual(handled, []); self.assertEqual(writes, [])
                self.assertEqual(counts, {'workload': 1})

    def test_raw_stream_bounded_before_budget_or_handler(self):
        from manual_research import MutationBudget
        # An otherwise permitted body padded beyond the total raw JSON bound.
        import json
        raw = json.dumps(payload()).encode() + b' ' * (2 * 1024 * 1024)
        status, remaining, handled, writes, _ = self.boundary(raw, chunks=[raw[:100], raw[100:]])
        self.assertEqual(status, 403); self.assertEqual(remaining, MutationBudget().remaining)
        self.assertEqual(handled, []); self.assertEqual(writes, [])

    def test_real_shim_admits_exact_raw_bytes_and_preserves_old_profiles(self):
        import json
        raw = json.dumps(payload()).encode()
        status, remaining, handled, writes, counts = self.boundary(raw, chunks=[raw[:11], raw[11:]])
        self.assertEqual(status, 201); self.assertEqual(remaining[PATH], 1)
        self.assertEqual(len(handled), 1); self.assertEqual(handled[0]._body, raw)
        self.assertEqual(writes[0]['request'], payload()); self.assertEqual(counts, {'workload': 0})
        for profile in ('readonly', 'authoring-v1'):
            status, _, handled, writes, _ = self.boundary(raw, profile=profile)
            self.assertEqual(status, 403); self.assertEqual(handled, []); self.assertEqual(writes, [])
        authoring = b'{"idempotency_key":"old-profile","yaml_text":"inert"}'
        status, _, handled, writes, _ = self.boundary(authoring, '/api/editor/save', 'authoring-v1')
        self.assertEqual(status, 201); self.assertEqual(len(handled), 1)
        self.assertEqual(writes[0]['request'], json.loads(authoring))
        status, _, handled, _, _ = self.boundary(authoring, '/api/editor/save', 'readonly')
        self.assertEqual(status, 403); self.assertEqual(handled, [])

    def test_raw_invalid_json_and_queries_never_dispatch(self):
        import json
        from manual_research import MutationBudget
        raw = json.dumps(payload()).encode()
        for invalid in (b'{', b'null', b'[]', b'\xff', b'['*2000 + b']'*2000,
                        raw.replace(b'null', b'NaN'), raw.replace(b'manual-test', br'\ud800')):
            status, remaining, handled, writes, _ = self.boundary(invalid)
            self.assertEqual(status, 403); self.assertEqual(remaining, MutationBudget().remaining)
            self.assertEqual(handled, []); self.assertEqual(writes, [])
        status, remaining, handled, writes, _ = self.boundary(raw, PATH + '?x=1')
        self.assertEqual(status, 403); self.assertEqual(remaining, MutationBudget().remaining)
        self.assertEqual(handled, []); self.assertEqual(writes, [])

    def allowed(self, method='POST', path=PATH, body=None, profile=PROFILE):
        counts = {'workload': 0}
        result = api.workload_allowed(method, path, counts, profile, body)
        self.assertEqual(counts['workload'], int(not result))
        return result

    def test_exact_manual_save_only(self):
        self.assertTrue(self.allowed(body=payload()))
        child = payload(); child['parent_revision_id'] = 'd' * 32
        self.assertTrue(self.allowed(body=child))

    def test_negative_body_and_route_boundaries(self):
        mutations = [lambda b: b.pop('parent_revision_id'),
                     lambda b: b.update(publication_target={}),
                     lambda b: b.update(source_job_id='a' * 32),
                     lambda b: b.update(grant='inert'),
                     lambda b: b.update(parent_revision_id=False),
                     lambda b: b.update(parent_revision_id='latest'),
                     lambda b: b.update(family='../escape'),
                     lambda b: b.update(idempotency_key=''),
                     lambda b: b['source'].update(kind='accepted_candidate'),
                     lambda b: b['source'].update(bundle_sha256='d' * 64),
                     lambda b: b['source'].update(source_hash='B' * 64),
                     lambda b: b['source'].update(editor_revision_id='bad')]
        for mutate in mutations:
            b = payload(); mutate(b)
            with self.subTest(body=b): self.assertFalse(self.allowed(body=b))
        for path in [PATH + '/', PATH + '/x', PATH.replace('manual-browser', 'other'),
                     '/api/editor/generate', '/api/jobs', '/api/editor/snapshots',
                     '/api/research/publication-targets', '/api/settings/models',
                     '/api/workflow-grants', '/api/research/stores/manual-browser/versions?x=1']:
            with self.subTest(path=path): self.assertFalse(self.allowed(path=path, body=payload()))
        for method in ['PUT', 'PATCH', 'DELETE']:
            self.assertFalse(self.allowed(method=method, body=payload()))
        for body in [None, [], {}, 'bad']:
            self.assertFalse(self.allowed(body=body))

    def test_mutation_budget_reserves_before_dispatch_and_never_resets(self):
        import manual_research as m
        self.assertTrue(hasattr(m, 'MutationBudget'), 'manual dispatch budget missing')
        budget = m.MutationBudget()
        self.assertTrue(budget.admit('/api/editor/save'))
        self.assertFalse(budget.admit('/api/editor/save'))
        self.assertFalse(budget.admit('/api/jobs'))
        self.assertTrue(budget.admit(PATH)); self.assertTrue(budget.admit(PATH))
        self.assertFalse(budget.admit(PATH))

    def test_old_profiles_never_admit_manual(self):
        for profile in ['readonly', 'authoring-v1']:
            self.assertFalse(self.allowed(body=payload(), profile=profile))

    def test_manual_editor_save_requires_exact_frozen_body(self):
        body = {'idempotency_key': 'browser-key', 'yaml_text': 'inert: true\n',
                'document_id': 'a' * 32, 'expected_source_hash': 'b' * 64}
        self.assertTrue(self.allowed(path='/api/editor/save', body=body))
        for mutate in [lambda b: b.update(publication_target={}), lambda b: b.pop('document_id'),
                       lambda b: b.update(expected_source_hash=False), lambda b: b.update(yaml_text='')]:
            b = copy.deepcopy(body); mutate(b)
            self.assertFalse(self.allowed(path='/api/editor/save', body=b))


def proof_fixture():
    """Deliberately synthetic, memory-only checker inputs; no proof files/pixels."""
    import hashlib
    import json
    sha = lambda x: hashlib.sha256(x.encode()).hexdigest()
    canonical = lambda x: json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    text = '# unit-only\ninert: true\n'
    cap = {'durable_editor_save': True, 'research_versions': True, 'manual_research_save': True,
           'research_version_open': True, 'generation': False, 'snapshots': False, 'neo4j': False,
           'publication_execution': False}
    api_proof = {'profile': PROFILE, 'view_id': 'a' * 32, 'source_hash': sha('original'), 'capabilities': cap,
                 'manual_store': {'store_id': 'manual-browser', 'registry_id': 'unit-registry', 'root': '/private/manual-research',
                                  'existing_app_journal': True, 'fresh': True, 'closed': True}}
    wires = []
    def wire(method, path, body, response, status=200):
        n = len(wires) + 1
        r = {'sequence': n, 'method': method, 'path': path, 'target': path, 'status': status,
             'response_request_sequence': n, 'response': copy.deepcopy(response)}
        if body is not None: r.update(request=copy.deepcopy(body), request_body=json.dumps(body))
        wires.append(r)
        return n
    health = wire('GET', '/api/health', None, {'capabilities': {'durable_editor_save': True, 'generation': False, 'preview': False, 'diagnostic': False}})
    index = wire('GET', '/api/editor', None, {'capabilities': cap})
    stores = wire('GET', '/api/research/stores', None, {'stores': [{'store_id': 'manual-browser', 'available': True}]})
    savebody = {'idempotency_key': 'editor-test', 'yaml_text': text, 'document_id': api_proof['view_id'], 'expected_source_hash': api_proof['source_hash']}
    revision_id = sha(savebody['idempotency_key'])[:32]
    rev = {'revision_id': revision_id, 'yaml_text': text, 'source_hash': sha(text), 'canonical_hash': sha('canonical'),
           'download_url': f'/api/editor/revisions/{revision_id}/download',
           'open_source': {'kind': 'editor_revision', 'id': 'editor-revision:' + revision_id}}
    receipt = {'schema_version': 1, 'state': 'committed', 'idempotency_key': savebody['idempotency_key'],
               'request_sha256': sha(json.dumps(['editor-save/v1', text, api_proof['view_id'], api_proof['source_hash']], separators=(',', ':'), ensure_ascii=False)), 'revision': rev}
    vrequest = {'yaml_text': text, 'document_id': api_proof['view_id']}
    validation = wire('POST', '/api/editor/validate', vrequest, {'valid': True, 'source_hash': sha(text), 'canonical_hash': rev['canonical_hash']})
    save = wire('POST', '/api/editor/save', savebody, receipt)
    save_get = wire('GET', '/api/editor/save-requests/editor-test', None, receipt)
    source = {'kind': 'editor_revision', 'editor_revision_id': rev['revision_id'], 'source_hash': sha(text), 'canonical_hash': rev['canonical_hash'],
              'schema_version': 1, 'bundle_codec': 'arena-editor-bundle/v1', 'bundle_sha256': sha('bundle'), 'receipt_sha256': sha('receipt')}
    versions = []
    for n in [1, 2]:
        body = payload(); body.update(idempotency_key=f'manual-{n}', source={k: source[k] for k in payload()['source']},
                                      parent_revision_id=None if n == 1 else 'c' * 32)
        reservation = {'store_id': 'manual-browser', 'family': 'browser-family', 'workflow_id': body['idempotency_key'],
                       'reservation_id': str(n) * 32, 'revision_id': ('c' if n == 1 else 'd') * 32, 'version': n,
                       'parent_revision_id': body['parent_revision_id'], 'source': source, 'registry_id': 'unit-registry',
                       'approval': {'scope': 'persist_editor_revision', 'principal': 'single_operator_workspace'}}
        reservation.update(schema_version=1, publication_request=None)
        reservation['request_digest'] = sha(canonical({k: reservation[k] for k in ('store_id', 'family', 'source', 'parent_revision_id', 'publication_request')}))
        manifest = {'schema': 1, 'store_id': 'manual-browser', 'registry_id': 'unit-registry', 'reservation_id': reservation['reservation_id'],
                    'binding': reservation, 'files': {'environment.yaml': {'size': len(text.encode()), 'sha256': sha(text)}}}
        manifest['digest'] = sha(canonical(manifest))
        commit = {'reservation': reservation, 'manifest': manifest, 'relative_directory': f'final/browser-family/v{n}', 'publication_intent_id': None}
        before = len(wires)
        post = wire('POST', PATH, body, commit, 201)
        get = wire('GET', PATH + '/' + reservation['reservation_id'], None, commit)
        versions.append({'before': before, 'post': post, 'get': get,
                         'parent_choice': 'none' if n == 1 else 'c'*32,
                         'parent_selection': None if n == 1 else selected_parent})
        if n == 1: selected_parent = wire('GET', PATH + '/' + reservation['reservation_id'], None, commit)
    commit = wires[versions[-1]['post']-1]['response']; r = commit['reservation']
    identity = {k: r[k] for k in ['store_id', 'reservation_id', 'revision_id', 'family', 'version', 'source']}
    identity['manifest_digest'] = commit['manifest']['digest']
    descriptor = f"research-version:manual-browser:{r['reservation_id']}:{identity['manifest_digest']}"
    loaded = {'document_id': 'e' * 32, 'source': descriptor, 'source_origin': {'kind': 'research_version', 'id': descriptor},
              'research_identity': identity, 'yaml_text': text, 'source_hash': sha(text),
              'validation': {'valid': True, 'source_hash': sha(text), 'canonical_hash': rev['canonical_hash']}}
    selection = wire('GET', PATH + '/' + r['reservation_id'], None, commit)
    cancel = {'before': len(wires), 'after': len(wires), 'yaml_before': text + '# dirty\n', 'yaml_after': text + '# dirty\n', 'dialog': 'dismissed'}
    opened = wire('GET', '/api/editor/documents/' + descriptor, None, loaded)
    loaded['document_id'] = 'f' * 32
    reloaded = wire('GET', '/api/editor/documents/' + descriptor, None, loaded)
    recovery_draft = text + '# recover\n'
    loaded['document_id'] = '0' * 32
    recovery_load = wire('GET', '/api/editor/documents/' + descriptor, None, loaded)
    restore_before = len(wires)
    restore_validation = wire('POST', '/api/editor/validate', {'yaml_text': recovery_draft, 'document_id': loaded['document_id']},
                              {'valid': True, 'source_hash': sha(recovery_draft), 'canonical_hash': rev['canonical_hash']})
    jobs = wire('GET', '/api/jobs', None, {'jobs': []})
    a = {'schema_version': 1, 'status': 'passed', 'profile': PROFILE, 'remaining': [], 'exchanges': wires,
         'health': health, 'index': index, 'stores': stores, 'validation': validation, 'save': save, 'save_get': save_get, 'versions': versions,
         'selected_get': selection, 'open': opened, 'reload': reloaded, 'recovery_load': recovery_load, 'jobs': jobs,
         'draft': text, 'draft_sha256': sha(text), 'cancel': cancel,
         'no_parent': {'before': save_get, 'after': save_get, 'save_disabled': True},
         'no_auto_open': {'before': save, 'after': selection, 'yaml': text},
         'recovery': {'before': restore_before, 'validation': restore_validation, 'draft': recovery_draft,
                      'root_before_restore': text, 'draft_before_reload': recovery_draft, 'restored': recovery_draft, 'explicit': True},
         'reload_context': {'prompt': 'manual context', 'explicit': True, 'root': text,
                            'backup': {'version': 1, 'documentId': descriptor, 'viewId': 'e'*32, 'sourceHash': sha(text), 'researchIdentity': identity, 'draft': text, 'prompt': 'manual context'}},
         'automatic_previews': False, 'open_yaml': text, 'reload_yaml': text,
         'download': {'artifact': 'manual-research-root.yaml', 'bytes': len(text.encode()), 'sha256': sha(text), 'url_scheme': 'blob:'}}
    a['recovery']['backup'] = {'version': 1, 'documentId': descriptor, 'viewId': 'f'*32, 'sourceHash': sha(text), 'researchIdentity': identity, 'draft': recovery_draft, 'prompt': 'manual context'}
    final = {'profile': PROFILE, 'allowed_authoring_writes': [{'method': 'POST', 'path': '/api/editor/save', 'request': savebody, 'status': 200}],
             'allowed_manual_writes': [{'method': 'POST', 'path': PATH, 'request': wires[v['post']-1]['request'], 'status': 201} for v in versions],
             'manual_store': copy.deepcopy(api_proof['manual_store']), 'manual_versions': [copy.deepcopy(wires[v['post']-1]['response']) for v in versions]}
    return a, api_proof, final


def v2_proof_fixture():
    """Synthetic v2 records on the unchanged full v1 journey wire fixture."""
    data = copy.deepcopy(proof_fixture())
    # Controller lifetimes need not share a draft ID or monotonic revision.
    data[0]['reload_context']['backup'].update(
        version=2, draftId='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', revision=9007199254740991)
    data[0]['recovery']['backup'].update(
        version=2, draftId='01234567-89ab-cdef-0123-456789abcdef', revision=0)
    return data


def artifact_fixture():
    import manual_research as m
    import json
    a, _, _ = proof_fixture()
    receipt = a['exchanges'][a['save']-1]['response']
    commit = a['exchanges'][a['versions'][0]['post']-1]['response']
    source = commit['reservation']['source']
    body = a['exchanges'][a['save']-1]['request']
    snapshot = {'yaml_text': a['draft'], 'source_hash': source['source_hash'], 'canonical_hash': source['canonical_hash'],
                'includes': {}, 'document_id': body['document_id'], 'expected_source_hash': body['expected_source_hash']}
    export = 'inert: true\n'
    source['bundle_sha256'] = m.sha(m.canonical(['arena-editor-bundle/v1', receipt, snapshot, export]))
    source['receipt_sha256'] = m.sha(json.dumps(receipt, sort_keys=True, separators=(',', ':'), ensure_ascii=True))
    files = {'environment.yaml': a['draft'].encode(), 'editor-receipt.json': m.canonical(receipt).encode(),
             'editor-snapshot.json': m.canonical(snapshot).encode(), 'export.yaml': export.encode(),
             'source.json': json.dumps(commit['reservation'], sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()}
    reseal_artifact(commit, files, receipt, snapshot)
    return commit, files, receipt


def saved_body_fixture():
    a, _, _ = proof_fixture()
    return a['exchanges'][a['save']-1]['request']


def reseal_artifact(commit, files, receipt, snapshot):
    """Reseal every synthetic leaf and containing digest after semantic tampering."""
    import manual_research as m
    import json
    registry_json = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    source = commit['reservation']['source']
    source['bundle_sha256'] = m.sha(m.canonical(['arena-editor-bundle/v1', receipt, snapshot, files['export.yaml'].decode()]))
    source['receipt_sha256'] = m.sha(registry_json(receipt))
    files['editor-snapshot.json'] = m.canonical(snapshot).encode()
    files['editor-receipt.json'] = m.canonical(receipt).encode()
    requested = {k: commit['reservation'][k] for k in ('store_id', 'family', 'source', 'parent_revision_id', 'publication_request')}
    commit['reservation']['request_digest'] = m.sha(registry_json(requested))
    files['source.json'] = registry_json(commit['reservation'])
    manifest = commit['manifest']; manifest['binding'] = copy.deepcopy(commit['reservation'])
    manifest['files'] = {name: {'size': len(raw), 'sha256': m.sha(raw)} for name, raw in files.items()}
    manifest['digest'] = m.sha(registry_json({k: v for k, v in manifest.items() if k != 'digest'}))


class ManualBootstrapTests(unittest.TestCase):
    def test_bootstrap_uses_existing_journal_and_closes_only_store(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import Mock
        self.assertTrue(hasattr(api, 'bootstrap_manual_store'), 'manual store bootstrap missing')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'fresh'
            journal, protect = object(), object()
            app = SimpleNamespace(state=SimpleNamespace(journal=journal, model_settings=SimpleNamespace(protect_public=protect), research_roots={'manual-browser': root}))
            store = Mock(); store.registry.registry_id = 'unit-registry'; store.registry.journal = journal
            store.store_id = 'manual-browser'
            cls = Mock(); cls.create.return_value = store
            result = api.bootstrap_manual_store(app, cls)
            cls.create.assert_called_once_with(journal, root, 'manual-browser', protect_public=protect)
            store.close.assert_called_once_with()
            self.assertTrue(result['existing_app_journal'])
            self.assertEqual(result.get('registry_id'), 'unit-registry')
            root.mkdir()
            with self.assertRaises(AssertionError): api.bootstrap_manual_store(app, cls)

    def test_store_identity_rejects_foreign_journal_store_and_invalid_registry(self):
        from types import SimpleNamespace
        journal = object(); app = SimpleNamespace(state=SimpleNamespace(journal=journal))
        for other_journal, store_id, registry_id in [(object(), 'manual-browser', 'unit-registry'),
                (journal, 'other-store', 'unit-registry'), (journal, 'manual-browser', False),
                (journal, 'manual-browser', '../registry')]:
            store = SimpleNamespace(store_id=store_id, registry=SimpleNamespace(journal=other_journal, registry_id=registry_id))
            with self.assertRaises(AssertionError): api.manual_store_identity(app, store)

    def test_manual_runner_requires_both_closures_and_browser_v7(self):
        from unittest import mock
        import run
        for args in [[], ['--browser'], ['--browser', '--layout', 'v7']]:
            with mock.patch.object(run, 'discover') as discover, self.assertRaises(SystemExit) as e:
                run.main(['--profile', PROFILE, *args])
            self.assertEqual(e.exception.code, 2); discover.assert_not_called()


class ManualProofTests(unittest.TestCase):
    def check(self, data):
        import manual_research
        self.assertTrue(hasattr(manual_research, 'contract'), 'manual strict contract missing')
        manual_research.contract(*data)

    def test_synthetic_contract(self):
        self.check(proof_fixture())

    def test_synthetic_v2_backups_preserve_full_manual_wire_contract(self):
        self.check(v2_proof_fixture())

    def test_synthetic_mixed_backups_do_not_invent_migration_guarantees(self):
        for phase in ('reload_context', 'recovery'):
            data = v2_proof_fixture()
            data[0][phase]['backup'] = copy.deepcopy(proof_fixture()[0][phase]['backup'])
            self.check(data)
        data = v2_proof_fixture()
        data[0]['recovery']['backup'].update(
            draftId=data[0]['reload_context']['backup']['draftId'], revision=0)
        self.check(data)

    def test_v2_backup_metadata_requires_exact_uuid_and_safe_integer(self):
        cases = {
            'draftId': [None, False, 1, {}, [], '', 'a'*32,
                        'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE',
                        'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeeg',
                        'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n',
                        'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee-extra'],
            'revision': [None, False, True, -1, 9007199254740992, 0.5, 1.0, '0', {}, []],
        }
        for phase in ('reload_context', 'recovery'):
            for field, values in cases.items():
                for value in values:
                    data = v2_proof_fixture(); data[0][phase]['backup'][field] = value
                    with self.subTest(phase=phase, field=field, value=value), self.assertRaisesRegex(
                            AssertionError, 'Draft backup (draftId|revision) invalid'):
                        self.check(data)

    def test_backup_version_and_exact_fieldsets_for_both_phases(self):
        for fixture in (proof_fixture, v2_proof_fixture):
            for phase in ('reload_context', 'recovery'):
                backup = fixture()[0][phase]['backup']
                for field in backup:
                    data = fixture(); del data[0][phase]['backup'][field]
                    with self.subTest(fixture=fixture.__name__, phase=phase, missing=field), self.assertRaises(AssertionError):
                        self.check(data)
                extras = {'extra': None, 'rootHash': backup['sourceHash']}
                if backup['version'] == 1:
                    extras.update(draftId='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', revision=0)
                for field, value in extras.items():
                    data = fixture(); data[0][phase]['backup'][field] = value
                    with self.subTest(phase=phase, extra=field), self.assertRaises(AssertionError):
                        self.check(data)
                for value in (None, False, True, 0, 3, '1', '2', 1.0, 2.0, {}, []):
                    data = fixture(); data[0][phase]['backup']['version'] = value
                    with self.subTest(phase=phase, version=value), self.assertRaisesRegex(AssertionError, 'Draft backup version invalid'):
                        self.check(data)
                for value in (None, False, [], 'backup'):
                    data = fixture(); data[0][phase]['backup'] = value
                    with self.subTest(phase=phase, object=value), self.assertRaisesRegex(AssertionError, 'Draft backup object required'):
                        self.check(data)

    def test_v1_v2_backups_keep_exact_source_and_recovery_evidence(self):
        changes = [('documentId', 'research-version:manual-browser:' + '9'*32 + ':' + '0'*64),
                   ('viewId', '9'*32), ('sourceHash', '0'*64), ('draft', 'wrong root\n'),
                   ('prompt', 'wrong prompt'), ('researchIdentity', {})]
        for fixture in (proof_fixture, v2_proof_fixture):
            for phase in ('reload_context', 'recovery'):
                for field, value in changes + [(k, False) for k, _ in changes]:
                    data = fixture(); data[0][phase]['backup'][field] = value
                    with self.subTest(fixture=fixture.__name__, phase=phase, field=field, value=value), self.assertRaisesRegex(
                            AssertionError, 'Exact typed JSON readback mismatch'):
                        self.check(data)
                for field, value in [('version', True), ('manifest_digest', '0'*64), ('source', {})]:
                    data = fixture()
                    # Detach shared synthetic identity so the observed source stays intact.
                    backup = copy.deepcopy(data[0][phase]['backup'])
                    backup['researchIdentity'][field] = value; data[0][phase]['backup'] = backup
                    with self.subTest(phase=phase, identity=field), self.assertRaisesRegex(AssertionError, 'Exact typed JSON readback mismatch'):
                        self.check(data)
                data = fixture()
                other = 'recovery' if phase == 'reload_context' else 'reload_context'
                data[0][phase]['backup'] = copy.deepcopy(data[0][other]['backup'])
                with self.subTest(phase=phase, swapped=True), self.assertRaisesRegex(AssertionError, 'Exact typed JSON readback mismatch'):
                    self.check(data)

    def test_backup_field_limits_count_utf16_not_codepoints_or_utf8(self):
        from manual_research import backup_contract
        # Object-only seam proves decoded field bounds, NOT raw storage JSON size.
        for fixture in (proof_fixture, v2_proof_fixture):
            for field, limit in (('draft', 262144), ('prompt', 16000)):
                for char, count in (('x', limit), ('é', limit), ('😀', limit // 2)):
                    backup = copy.deepcopy(fixture()[0]['recovery']['backup'])
                    backup[field] = char * count
                    expected = {k: v for k, v in backup.items() if k not in ('version', 'draftId', 'revision')}
                    backup_contract(backup, expected)
                    backup[field] += 'x'; expected[field] = backup[field]
                    with self.subTest(version=backup['version'], field=field, char=char), self.assertRaisesRegex(
                            AssertionError, 'Draft backup field limit exceeded'):
                        backup_contract(backup, expected)

    def test_full_wire_rejects_overlimit_prompt_even_with_matching_backups(self):
        for fixture in (proof_fixture, v2_proof_fixture):
            data = fixture(); prompt = '😀' * 8000 + 'x'
            data[0]['reload_context']['prompt'] = prompt
            for phase in ('reload_context', 'recovery'):
                data[0][phase]['backup']['prompt'] = prompt
            with self.assertRaisesRegex(AssertionError, 'Draft backup field limit exceeded'):
                self.check(data)

    def test_captured_targets_must_be_exact_query_free_paths(self):
        for field in ('save', 'index'):
            for suffix in ('?x=1', '?', '#', '#fragment'):
                data = proof_fixture(); a = data[0]
                row = a['exchanges'][a[field]-1]; row['target'] += suffix
                with self.subTest(field=field, suffix=suffix), self.assertRaisesRegex(AssertionError, 'Exact query-free target'):
                    self.check(data)

    def test_documented_read_queries_preserve_exact_path_binding(self):
        for path, query in ((PATH, 'family=browser-family&after_version=0&limit=25'),
                            ('/api/editor/previews/' + 'a'*64, 'view=isometric&resolution=1024&asset_views=%7B%7D')):
            data = proof_fixture(); rows = data[0]['exchanges']; sequence = len(rows) + 1
            row = {'sequence': sequence, 'method': 'GET', 'path': path, 'target': path + '?' + query,
                   'status': 200, 'response_request_sequence': sequence, 'response': {}}
            rows.append(row)
            with self.subTest(path=path):
                self.check(data)
                for target in (row['target'] + '#fragment', 'https://outside.invalid' + row['target'],
                               '/api/wrong-path?' + query):
                    changed = copy.deepcopy(data); changed[0]['exchanges'][-1]['target'] = target
                    with self.assertRaises(AssertionError): self.check(changed)
                for method in ('POST', 'PUT', 'DELETE'):
                    changed = copy.deepcopy(data); changed[0]['exchanges'][-1]['method'] = method
                    with self.assertRaisesRegex(AssertionError, 'Exact query-free target'):
                        self.check(changed)

    def test_real_metadata_and_persisted_recovery_identity_required(self):
        changes = [lambda a: a.pop('health'),
                   lambda a: a['exchanges'][a['health']-1]['response']['capabilities'].update(durable_editor_save=False),
                   lambda a: a['recovery']['backup'].update(viewId='retired'),
                   lambda a: a['recovery']['backup'].update(sourceHash='0'*64),
                   lambda a: a['recovery']['backup'].update(researchIdentity={}),
                   lambda a: a['reload_context'].update(explicit=False)]
        for change in changes:
            data = copy.deepcopy(proof_fixture()); change(data[0])
            with self.assertRaises((AssertionError, KeyError)): self.check(data)

    def test_resealed_cross_registry_lineage_rejected(self):
        import json
        import manual_research as m
        data = proof_fixture(); a, _, final = data
        # Change every v1 mirror and reseal its manifest, so no stale mirror or
        # digest can hide acceptance of two individually valid registry IDs.
        for row in a['exchanges']:
            commit = row['response']
            if type(commit) is dict and commit.get('relative_directory') == 'final/browser-family/v1':
                commit['reservation']['registry_id'] = 'other-registry'
                manifest = commit['manifest']; manifest['registry_id'] = 'other-registry'
                manifest['binding'] = copy.deepcopy(commit['reservation'])
                manifest['digest'] = m.sha(json.dumps({k: v for k, v in manifest.items() if k != 'digest'}, sort_keys=True, separators=(',', ':'), ensure_ascii=True))
        final['manual_versions'] = [copy.deepcopy(a['exchanges'][v['post']-1]['response']) for v in a['versions']]
        with self.assertRaisesRegex(AssertionError, 'Observed registry lineage'):
            self.check(data)

    def test_parent_requires_explicit_verified_selection(self):
        for value in (None, 1, True):
            data = proof_fixture(); data[0]['versions'][1]['parent_selection'] = value
            with self.subTest(value=value), self.assertRaises((AssertionError, KeyError)):
                self.check(data)

    def test_copied_artifact_hashes_and_bundle_are_independently_verified(self):
        import manual_research as m
        self.assertTrue(hasattr(m, 'artifact_contract'), 'copied artifact checker missing')
        commit, files, receipt = artifact_fixture()
        m.artifact_contract(commit, files, receipt, saved_body_fixture())
        for name in files:
            altered = dict(files); altered[name] += b' '
            with self.subTest(name=name), self.assertRaises(AssertionError):
                m.artifact_contract(commit, altered, receipt, saved_body_fixture())
        for key in ['bundle_sha256', 'receipt_sha256', 'canonical_hash']:
            altered = copy.deepcopy(commit); altered['reservation']['source'][key] = '0' * 64
            with self.subTest(key=key), self.assertRaises(AssertionError):
                m.artifact_contract(altered, files, receipt, saved_body_fixture())

    def test_resealed_snapshot_source_and_request_identity(self):
        import json
        import manual_research as m
        changes = [lambda s, r: s.pop('document_id'), lambda s, r: s.pop('expected_source_hash'),
                   lambda s, r: s.update(document_id='9'*32), lambda s, r: s.update(expected_source_hash='9'*64),
                   lambda s, r: s.update(document_id=None), lambda s, r: s.update(expected_source_hash=None),
                   lambda s, r: s.update(document_id=False), lambda s, r: s.update(expected_source_hash=True),
                   lambda s, r: s.update(extra=None), lambda s, r: s.update(includes=[]),
                   lambda s, r: s.update(includes={'a': False}), lambda s, r: s.update(includes={'/absolute': 'inert'}),
                   lambda s, r: s.update(includes={'a': 'x', 'b': 'y'}),
                   lambda s, r: r.update(request_sha256='9'*64),
                   lambda s, r: r['revision'].update(download_url='/wrong'),
                   lambda s, r: r.update(extra=None)]
        for n, change in enumerate(changes):
            commit, files, receipt = artifact_fixture(); snapshot = json.loads(files['editor-snapshot.json'])
            change(snapshot, receipt); reseal_artifact(commit, files, receipt, snapshot)
            with self.subTest(n=n), self.assertRaises((AssertionError, KeyError, ValueError)):
                m.artifact_contract(commit, files, receipt, saved_body_fixture())

    def test_snapshot_binds_captured_save_body_even_after_request_reseal(self):
        import inspect
        import json
        import manual_research as m
        self.assertIn('saved_request', inspect.signature(m.artifact_contract).parameters,
                      'Copied snapshot must receive the captured save request')
        for document_id in ('a'*32, None):
            for source_hash in ('b'*64, None):
                commit, files, receipt = artifact_fixture(); snapshot = json.loads(files['editor-snapshot.json'])
                snapshot.update(document_id=document_id, expected_source_hash=source_hash)
                body = {k: snapshot[k] for k in ('yaml_text', 'document_id', 'expected_source_hash')}
                body['idempotency_key'] = receipt['idempotency_key']
                receipt['request_sha256'] = m.sha(m.canonical(['editor-save/v1', snapshot['yaml_text'], document_id, source_hash]))
                reseal_artifact(commit, files, receipt, snapshot)
                m.artifact_contract(commit, files, receipt, body)
                for field, other in [('document_id', '9'*32 if document_id is None else None),
                                     ('expected_source_hash', '9'*64 if source_hash is None else None)]:
                    altered = dict(snapshot); altered[field] = other
                    changed = copy.deepcopy(receipt)
                    changed['request_sha256'] = m.sha(m.canonical(['editor-save/v1', altered['yaml_text'], altered['document_id'], altered['expected_source_hash']]))
                    reseal_artifact(commit, files, changed, altered)
                    with self.subTest(document_id=document_id, source_hash=source_hash, field=field), self.assertRaisesRegex(AssertionError, 'Captured save body'):
                        m.artifact_contract(commit, files, changed, body)

    def test_resealed_revision_id_must_derive_from_key(self):
        import json
        import manual_research as m
        commit, files, receipt = artifact_fixture(); snapshot = json.loads(files['editor-snapshot.json'])
        revision = receipt['revision']; revision['revision_id'] = '9'*32
        revision['download_url'] = '/api/editor/revisions/' + '9'*32 + '/download'
        revision['open_source']['id'] = 'editor-revision:' + '9'*32
        commit['reservation']['source']['editor_revision_id'] = '9'*32
        reseal_artifact(commit, files, receipt, snapshot)
        with self.assertRaisesRegex(AssertionError, 'Revision key identity'):
            m.artifact_contract(commit, files, receipt, saved_body_fixture())

    def test_duplicate_wire_keys_and_conflicting_success_are_rejected(self):
        data = proof_fixture(); a = data[0]
        r = a['exchanges'][a['save']-1]
        r['request_body'] = r['request_body'].replace('{', '{"yaml_text":"retired",', 1)
        with self.assertRaises((AssertionError, ValueError)): self.check(data)
        data = proof_fixture(); data[0]['error'] = 'journey failed'
        with self.assertRaises(AssertionError): self.check(data)

    def test_resealed_copied_source_cannot_invent_bundle_hash(self):
        import manual_research as m
        import json
        for field in ['bundle_sha256', 'receipt_sha256']:
            commit, files, receipt = artifact_fixture()
            commit['reservation']['source'][field] = '0' * 64
            files['source.json'] = json.dumps(commit['reservation'], sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
            commit['manifest']['files'] = {name: {'size': len(raw), 'sha256': m.sha(raw)} for name, raw in files.items()}
            with self.subTest(field=field), self.assertRaises(AssertionError): m.artifact_contract(commit, files, receipt, saved_body_fixture())

    def test_resealed_security_negatives(self):
        changes = [lambda a, p, f: a.update(status='failed'),
                   lambda a, p, f: a.update(profile='authoring-v1'),
                   lambda a, p, f: a.update(versions=a['versions'][:1]),
                   lambda a, p, f: a['exchanges'][a['save']-1]['request'].update(yaml_text='other'),
                   lambda a, p, f: a['exchanges'][a['save_get']-1].update(response_request_sequence=a['save']),
                   lambda a, p, f: a['versions'][0].update(get=a['versions'][0]['post']),
                   lambda a, p, f: a['exchanges'][a['versions'][0]['post']-1]['request'].pop('parent_revision_id'),
                   lambda a, p, f: a['exchanges'][a['versions'][0]['post']-1]['response']['reservation']['source'].update(bundle_sha256='0'*64),
                   lambda a, p, f: a['exchanges'][a['selected_get']-1]['response'].update(publication_intent_id='intent'),
                   lambda a, p, f: a['exchanges'][a['versions'][0]['post']-1]['response']['reservation'].update(request_digest='0'*64),
                   lambda a, p, f: a['exchanges'][a['versions'][0]['post']-1]['response']['reservation'].update(publication_request={}),
                   lambda a, p, f: a['exchanges'][a['open']-1]['response']['research_identity'].update(version=True),
                   lambda a, p, f: a['exchanges'][a['reload']-1]['response'].update(document_id='e'*32),
                   lambda a, p, f: a['cancel'].update(after=a['open']),
                   lambda a, p, f: a['recovery'].update(explicit=1),
                   lambda a, p, f: a['recovery'].update(root_before_restore='auto restored'),
                   lambda a, p, f: a['recovery'].update(validation=a['validation']),
                   lambda a, p, f: a['exchanges'][a['jobs']-1]['response'].update(jobs=[{}]),
                   lambda a, p, f: a['download'].update(sha256='0'*64),
                   lambda a, p, f: f.update(allowed_manual_writes=[]),
                   lambda a, p, f: f.update(manual_versions=[]),
                   lambda a, p, f: p['capabilities'].update(manual_research_save=False),
                   lambda a, p, f: p['manual_store'].update(existing_app_journal=False),
                   lambda a, p, f: a.update(automatic_previews=True)]
        for i, change in enumerate(changes):
            with self.subTest(i=i):
                data = copy.deepcopy(proof_fixture()); change(*data)
                with self.assertRaises((AssertionError, KeyError, ValueError)): self.check(data)


if __name__ == '__main__':
    unittest.main()
