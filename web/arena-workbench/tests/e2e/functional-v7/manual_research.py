# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Import-safe manual browser profile boundary; no production imports or execution."""
import re
import json
import hashlib
from urllib.parse import unquote, urlsplit


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def equal(a, b):
    assert canonical(a) == canonical(b), 'Exact typed JSON readback mismatch'


def backup_contract(backup, expected):
    """Bind parsed v1/v2 backups to independently observed phase fields."""
    assert type(backup) is dict, 'Draft backup object required'
    version = backup.get('version')
    assert type(version) is int and version in (1, 2), 'Draft backup version invalid'
    wanted = dict(expected)
    wanted['version'] = version
    if version == 2:
        draft_id, revision = backup.get('draftId'), backup.get('revision')
        assert matches(draft_id, r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'), 'Draft backup draftId invalid'
        assert type(revision) is int and 0 <= revision <= 9007199254740991, 'Draft backup revision invalid'
        # Metadata validates this record only, not cross-remount continuity.
        wanted.update(draftId=draft_id, revision=revision)
    equal(backup, wanted)  # Exact field set and typed source/YAML/prompt equality.
    assert all(type(backup[k]) is str for k in ('documentId', 'viewId', 'sourceHash', 'draft', 'prompt')), 'Draft backup string fields required'
    for field, limit in (('draft', 262144), ('prompt', 16000)):
        assert len(backup[field].encode('utf-16-le', errors='surrogatepass')) // 2 <= limit, 'Draft backup field limit exceeded'
    # The browser captures JSON.parse(raw), not raw. Reserializing cannot prove
    # parseDraft's 600000 (v1) / 601024 (v2) raw UTF-16 storage-record budgets.


def contract(a, api, final):
    """Require all manual journeys and bind actual request/response observations."""
    from check_proof import parse
    assert a['profile'] == api['profile'] == final['profile'] == PROFILE
    assert type(a['schema_version']) is int and a['schema_version'] == 1 and a['status'] == 'passed'
    assert not a.get('error') and not a.get('failure')
    assert a['remaining'] == [] and a['automatic_previews'] is False
    registry_id = api['manual_store']['registry_id']
    assert matches(registry_id, r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')
    store = {'store_id': STORE, 'registry_id': registry_id, 'root': '/private/manual-research', 'existing_app_journal': True, 'fresh': True, 'closed': True}
    equal(api['manual_store'], store); equal(final['manual_store'], store)
    rows = a['exchanges']; assert type(rows) is list and 0 < len(rows) <= 2000
    for n, row in enumerate(rows, 1):
        assert type(row['sequence']) is int and row['sequence'] == n
        # Only the documented read endpoints use query parameters. In particular,
        # a GET version list is not permission for a query-suffixed version POST.
        read_query = row['method'] in {'GET', 'HEAD'} and (
            row['path'] == VERSION_PATH or matches(row['path'], r'/api/editor/previews/[a-f0-9]{64}'))
        assert (row['path'] == urlsplit(row['target']).path and row['target'].startswith('/api/')
                and '#' not in row['target'] and (read_query or (
                    row['target'] == row['path'] and '?' not in row['target']))), 'Exact query-free target required outside admitted reads'
        if 'request' in row: equal(parse(row['request_body']), row['request'])
        if row['method'] not in {'GET', 'HEAD'}:
            assert row['method'] == 'POST' and (row['path'] in {'/api/session/activity', '/api/sessions', '/api/editor/validate'}
                                               or manual_mutation(row['method'], row['path'], row.get('request')))
        assert not any(word in row['path'] for word in ('/publication', '/grants', '/candidates/', '/generate', '/snapshots'))
    def exchange(n, method, path, status=200):
        assert type(n) is int and 1 <= n <= len(rows)
        row = rows[n-1]
        assert row['method'] == method and unquote(row['path']) == path
        assert type(row['status']) is int and row['status'] == status
        assert type(row['response_request_sequence']) is int and row['response_request_sequence'] == n
        assert not row.get('error')
        return row
    index = exchange(a['index'], 'GET', '/api/editor')['response']
    health = exchange(a['health'], 'GET', '/api/health')['response']['capabilities']
    assert health['durable_editor_save'] is True
    assert all(health[k] is False for k in ('generation', 'preview', 'diagnostic'))
    equal(index['capabilities'], api['capabilities'])
    for key in ('durable_editor_save', 'research_versions', 'manual_research_save', 'research_version_open'):
        assert index['capabilities'][key] is True
    for key in ('generation', 'snapshots', 'neo4j', 'publication_execution'):
        assert index['capabilities'][key] is False
    stores = exchange(a['stores'], 'GET', '/api/research/stores')['response']['stores']
    assert len(stores) == 1 and stores[0]['store_id'] == STORE and stores[0]['available'] is True
    text = a['draft']; assert type(text) is str and text and a['draft_sha256'] == sha(text)
    save = exchange(a['save'], 'POST', '/api/editor/save')
    assert manual_mutation('POST', save['path'], save['request'])
    expected = {'yaml_text': text, 'document_id': api['view_id'], 'expected_source_hash': api['source_hash'], 'idempotency_key': save['request']['idempotency_key']}
    equal(save['request'], expected)
    receipt = save['response']; revision = receipt['revision']
    assert type(receipt['schema_version']) is int and receipt['schema_version'] == 1 and receipt['state'] == 'committed'
    assert receipt['idempotency_key'] == expected['idempotency_key']
    assert receipt['request_sha256'] == sha(json.dumps(['editor-save/v1', text, api['view_id'], api['source_hash']], separators=(',', ':'), ensure_ascii=False))
    assert revision['yaml_text'] == text and revision['source_hash'] == sha(text)
    assert matches(revision['revision_id'], r'[a-f0-9]{32}') and matches(revision['canonical_hash'], r'[a-f0-9]{64}')
    equal(revision['open_source'], {'kind': 'editor_revision', 'id': 'editor-revision:' + revision['revision_id']})
    equal(exchange(a['save_get'], 'GET', '/api/editor/save-requests/' + expected['idempotency_key'])['response'], receipt)
    assert a['validation'] < a['save'] < a['save_get']
    def validation(n, yaml, view):
        row = exchange(n, 'POST', '/api/editor/validate')
        equal(row['request'], {'yaml_text': yaml, 'document_id': view})
        assert row['response']['valid'] is True and row['response']['source_hash'] == sha(yaml)
        assert row['response']['canonical_hash'] == revision['canonical_hash']
    validation(a['validation'], text, api['view_id'])
    versions = a['versions']; assert type(versions) is list and len(versions) == 2
    commits, posts = [], []
    previous = a['save_get']; source = None
    for number, phase in enumerate(versions, 1):
        assert type(phase['before']) is int and previous <= phase['before'] < phase['post'] < phase['get']
        if number == 1:
            assert phase['parent_selection'] is None and phase['parent_choice'] == 'none'
        else:
            assert type(phase['parent_selection']) is int and previous < phase['parent_selection'] <= phase['before']
            assert phase['parent_choice'] == commits[0]['reservation']['revision_id']
            equal(exchange(phase['parent_selection'], 'GET', VERSION_PATH + '/' + commits[0]['reservation']['reservation_id'])['response'], commits[0])
        post = exchange(phase['post'], 'POST', VERSION_PATH, 201); body = post['request']
        assert manual_mutation('POST', VERSION_PATH, body)
        commit = post['response']; r, m = commit['reservation'], commit['manifest']
        assert set(commit) == {'reservation', 'manifest', 'relative_directory', 'publication_intent_id'}
        assert commit['publication_intent_id'] is None and commit['relative_directory'] == f'final/{FAMILY}/v{number}'
        assert r['store_id'] == STORE and r['family'] == FAMILY and r['workflow_id'] == body['idempotency_key']
        assert type(r['version']) is int and r['version'] == number
        assert matches(r['reservation_id'], r'[a-f0-9]{32}') and matches(r['revision_id'], r'[a-f0-9]{32}')
        assert r['parent_revision_id'] == body['parent_revision_id'] == (None if number == 1 else commits[0]['reservation']['revision_id'])
        equal(r['approval'], {'scope': 'persist_editor_revision', 'principal': 'single_operator_workspace'})
        assert set(r) == {'schema_version', 'registry_id', 'reservation_id', 'revision_id', 'workflow_id', 'version',
                          'request_digest', 'store_id', 'family', 'source', 'parent_revision_id', 'approval', 'publication_request'}
        assert type(r['schema_version']) is int and r['schema_version'] == 1
        assert r['publication_request'] is None
        assert r['registry_id'] == registry_id, 'Observed registry lineage mismatch'
        requested = {k: r[k] for k in ('store_id', 'family', 'source', 'parent_revision_id', 'publication_request')}
        assert r['request_digest'] == sha(json.dumps(requested, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False))
        s = r['source']
        assert set(s) == {'kind', 'schema_version', 'editor_revision_id', 'source_hash', 'canonical_hash', 'bundle_codec', 'bundle_sha256', 'receipt_sha256'}
        assert type(s['schema_version']) is int and s['schema_version'] == 1 and s['bundle_codec'] == 'arena-editor-bundle/v1'
        assert matches(s['bundle_sha256'], r'[a-f0-9]{64}') and matches(s['receipt_sha256'], r'[a-f0-9]{64}')
        equal(body['source'], {'kind': 'editor_revision', 'editor_revision_id': revision['revision_id'], 'source_hash': sha(text), 'canonical_hash': revision['canonical_hash']})
        equal({k: s[k] for k in body['source']}, body['source'])
        if source is not None: equal(s, source)
        source = s
        assert set(m) == {'schema', 'store_id', 'registry_id', 'reservation_id', 'binding', 'files', 'digest'}
        assert type(m['schema']) is int and m['schema'] == 1
        for k in ('store_id', 'registry_id', 'reservation_id'): equal(m[k], r[k])
        equal(m['binding'], r)
        assert sha(json.dumps({k: v for k, v in m.items() if k != 'digest'}, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)) == m['digest']
        equal(m['files']['environment.yaml'], {'size': len(text.encode()), 'sha256': sha(text)})
        equal(exchange(phase['get'], 'GET', VERSION_PATH + '/' + r['reservation_id'])['response'], commit)
        commits.append(commit); posts.append(post); previous = phase['get']
    for field in ('reservation_id', 'revision_id'): assert commits[0]['reservation'][field] != commits[1]['reservation'][field]
    assert posts[0]['request']['idempotency_key'] != posts[1]['request']['idempotency_key']
    equal(final['manual_versions'], commits)
    for field, wanted in [('allowed_authoring_writes', [save]), ('allowed_manual_writes', posts)]:
        equal(final[field], [{k: r[k] for k in ('method', 'path', 'request', 'status')} for r in wanted])
    assert [r['sequence'] for r in rows if r['method'] == 'POST' and r['path'] == '/api/editor/save'] == [a['save']]
    assert [r['sequence'] for r in rows if r['method'] == 'POST' and r['path'] == VERSION_PATH] == [p['post'] for p in versions]
    r = commits[-1]['reservation']; descriptor = f"research-version:{STORE}:{r['reservation_id']}:{commits[-1]['manifest']['digest']}"
    equal(exchange(a['selected_get'], 'GET', VERSION_PATH + '/' + r['reservation_id'])['response'], commits[-1])
    assert previous < a['selected_get'] <= a['cancel']['before'] <= a['cancel']['after'] < a['open'] < a['reload'] < a['recovery_load']
    identity = {k: r[k] for k in ('store_id', 'reservation_id', 'revision_id', 'family', 'version', 'source')}
    identity['manifest_digest'] = commits[-1]['manifest']['digest']
    views = []
    for field in ('open', 'reload', 'recovery_load'):
        doc = exchange(a[field], 'GET', '/api/editor/documents/' + descriptor)['response']
        equal(doc['research_identity'], identity)
        equal(doc['source_origin'], {'kind': 'research_version', 'id': descriptor})
        assert doc['source'] == descriptor and doc['yaml_text'] == text and doc['source_hash'] == sha(text)
        assert doc['validation']['valid'] is True and doc['validation']['source_hash'] == sha(text)
        assert doc['validation']['canonical_hash'] == revision['canonical_hash']
        assert matches(doc['document_id'], r'[a-f0-9]{32}')
        views.append(doc['document_id'])
    assert len(set(views)) == 3, 'Each research GET requires a fresh UUID'
    assert [r['sequence'] for r in rows if r['sequence'] > a['save'] and r['path'].startswith('/api/editor/documents/')] == [a['open'], a['reload'], a['recovery_load']]
    assert a['open_yaml'] == a['reload_yaml'] == text
    for field in ('cancel', 'no_parent', 'no_auto_open'):
        phase = a[field]; before, after = phase['before'], phase['after']
        assert type(before) is int and type(after) is int and 0 <= before <= after <= len(rows)
        between = rows[before:after]
        if field == 'cancel': assert phase['dialog'] == 'dismissed' and phase['yaml_before'] == phase['yaml_after'] != text
        if field == 'no_parent':
            assert phase['save_disabled'] is True and a['save_get'] <= before <= after < versions[0]['post']
            assert not any(row['method'] == 'POST' and row['path'] == VERSION_PATH for row in between)
        else: assert not any(row['path'].startswith('/api/editor/documents/') for row in between)
        if field == 'no_auto_open': assert before == a['save'] and after == a['selected_get'] and phase['yaml'] == text
    recovery = a['recovery']
    context = a['reload_context']
    assert context['explicit'] is True and context['root'] == text
    assert type(context['prompt']) is str and context['prompt']
    for phase, view, draft in ((context, views[0], text), (recovery, views[1], recovery['draft'])):
        backup_contract(phase['backup'], {'documentId': descriptor, 'viewId': view, 'sourceHash': sha(text),
                                         'researchIdentity': identity, 'draft': draft, 'prompt': context['prompt']})
    assert recovery['explicit'] is True and recovery['root_before_restore'] == text
    assert recovery['draft'] == recovery['restored'] == recovery['draft_before_reload'] != text
    assert a['recovery_load'] <= recovery['before'] < recovery['validation'] < a['jobs']
    validation(recovery['validation'], recovery['draft'], views[-1])
    assert exchange(a['jobs'], 'GET', '/api/jobs')['response']['jobs'] == []
    download = a['download']
    assert download['artifact'] == 'manual-research-root.yaml' and download['url_scheme'] == 'blob:'
    assert type(download['bytes']) is int and download['bytes'] == len(text.encode()) and download['sha256'] == sha(text)
    return a

def artifact_contract(commit, files, saved_receipt, saved_request):
    """Recompute portable bundle/receipt/file hashes from actual copied bytes."""
    names = {'environment.yaml', 'editor-snapshot.json', 'editor-receipt.json', 'export.yaml', 'source.json'}
    assert set(files) == set(commit['manifest']['files']) == names
    for name, data in files.items():
        assert type(data) is bytes and 0 < len(data) <= 2 * 1024 * 1024
        equal(commit['manifest']['files'][name], {'size': len(data), 'sha256': sha(data)})
    receipt = json.loads(files['editor-receipt.json']); snapshot = json.loads(files['editor-snapshot.json'])
    equal(receipt, saved_receipt)
    # Identity/JSON shape mirrors Documents._verify_revision_parts and
    # editor_revision_storage.{encode,request_hash,key_id}; no Arena imports.
    assert type(receipt) is dict and set(receipt) == {'schema_version', 'state', 'idempotency_key', 'request_sha256', 'revision'}
    assert type(receipt['schema_version']) is int and receipt['schema_version'] == 1 and receipt['state'] == 'committed'
    assert matches(receipt['idempotency_key'], r'[A-Za-z0-9][A-Za-z0-9:._-]{0,127}')
    revision_id = sha(receipt['idempotency_key'])[:32]
    assert receipt['revision']['revision_id'] == revision_id, 'Revision key identity mismatch'
    assert type(snapshot) is dict and set(snapshot) == {'yaml_text', 'includes', 'source_hash', 'canonical_hash', 'document_id', 'expected_source_hash'}
    assert type(snapshot['yaml_text']) is str and len(snapshot['yaml_text'].encode()) <= 262144
    assert type(snapshot['includes']) is dict and len(snapshot['includes']) <= 1
    for name, included in snapshot['includes'].items():
        assert type(name) is str and not name.startswith('/')
        assert type(included) is str and len(included.encode()) <= 262144
    for field, pattern in [('document_id', r'[a-f0-9]{32}'), ('expected_source_hash', r'[a-f0-9]{64}')]:
        assert snapshot[field] is None or matches(snapshot[field], pattern)
    assert all(matches(snapshot[k], r'[a-f0-9]{64}') for k in ('source_hash', 'canonical_hash'))
    assert receipt['request_sha256'] == sha(canonical(['editor-save/v1', snapshot['yaml_text'], snapshot['document_id'], snapshot['expected_source_hash']])), 'Snapshot request identity mismatch'
    equal(receipt['revision'], {'revision_id': revision_id, 'yaml_text': snapshot['yaml_text'],
          'source_hash': snapshot['source_hash'], 'canonical_hash': snapshot['canonical_hash'],
          'download_url': f'/api/editor/revisions/{revision_id}/download',
          'open_source': {'kind': 'editor_revision', 'id': 'editor-revision:' + revision_id}})
    captured = {k: snapshot[k] for k in ('yaml_text', 'document_id', 'expected_source_hash')}
    captured['idempotency_key'] = receipt['idempotency_key']
    assert canonical(captured) == canonical(saved_request), 'Captured save body mismatch'
    assert files['editor-receipt.json'] == canonical(receipt).encode()
    assert files['editor-snapshot.json'] == canonical(snapshot).encode()
    equal(json.loads(files['source.json']), commit['reservation'])
    source = commit['reservation']['source']
    assert files['environment.yaml'] == snapshot['yaml_text'].encode() == receipt['revision']['yaml_text'].encode()
    assert source['source_hash'] == snapshot['source_hash'] == receipt['revision']['source_hash'] == sha(files['environment.yaml'])
    assert source['canonical_hash'] == snapshot['canonical_hash'] == receipt['revision']['canonical_hash']
    assert source['editor_revision_id'] == receipt['revision']['revision_id']
    assert source['bundle_sha256'] == sha(canonical([source['bundle_codec'], receipt, snapshot, files['export.yaml'].decode()]))
    assert source['receipt_sha256'] == sha(json.dumps(receipt, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False))


def proof(root, run, api, final, web):
    """Add manual checks to, never replace, the existing strict ownership envelope."""
    from check_proof import confined, HARNESS_PREFIX
    assert run['profile'] == web['profile'] == PROFILE
    assert run['browser'] is True and run['layout'] == 'v7' and run['mutations_enabled'] is True
    assert run['manual_research_closure_approved'] is True
    equal(run['allowed_mutations'], MUTATIONS)
    assert {HARNESS_PREFIX + n for n in ('browser-manual-research.mjs', 'manual_research.py', 'api.py', 'run.py', 'check_proof.py')} <= set(run['source_sha256'])
    a = contract(web['manual_research'], api, final)
    # Reconcile every mutation observed independently at the HTTP proxy boundary.
    rows = [r for r in web['http'] if r['method'] == 'POST' and r['path'] in ('/api/editor/save', VERSION_PATH)]
    equal(rows, [{'method': 'POST', 'path': '/api/editor/save', 'status': 200},
                 {'method': 'POST', 'path': VERSION_PATH, 'status': 201}, {'method': 'POST', 'path': VERSION_PATH, 'status': 201}])
    for row in web['http']:
        if row['method'] not in ('GET', 'HEAD'):
            assert row['method'] == 'POST' and row['path'] in ('/api/sessions', '/api/session/activity', '/api/editor/validate', '/api/editor/save', VERSION_PATH)
    expected_shots = ['manual-research-saved.png', 'manual-research-opened.png', 'manual-research-recovered.png']
    assert a['screenshots'] == expected_shots
    for name in expected_shots:
        path = 'evidence/' + name
        assert path in run['artifacts']
        raw = confined(root, path).read_bytes()
        assert len(raw) > 100 and raw.startswith(b'\x89PNG\r\n\x1a\n')
    download = 'evidence/' + a['download']['artifact']
    assert download in run['artifacts']
    assert confined(root, download).read_bytes() == a['draft'].encode()
    receipt = a['exchanges'][a['save']-1]['response']
    for n, commit in enumerate(final['manual_versions'], 1):
        files = {}
        for name in ('environment.yaml', 'editor-snapshot.json', 'editor-receipt.json', 'export.yaml', 'source.json'):
            path = f'evidence/manual-version-{n}/{name}'
            assert path in run['artifacts']
            files[name] = confined(root, path).read_bytes()
        artifact_contract(commit, files, receipt, a['exchanges'][a['save']-1]['request'])


PROFILE = 'manual-research-v1'
STORE = 'manual-browser'
FAMILY = 'browser-family'
VERSION_PATH = f'/api/research/stores/{STORE}/versions'
MUTATIONS = ['keyed-editor-save-fresh-private-state', 'manual-numbered-save-fresh-private-store']


class MutationBudget:
    """Reserve each attempt before awaiting dispatch; failed attempts consume budget."""
    def __init__(self):
        self.remaining = {'/api/editor/save': 1, VERSION_PATH: 2}

    def admit(self, path):
        if self.remaining.get(path, 0) == 0:
            return False
        self.remaining[path] -= 1
        return True


def matches(value, pattern):
    return type(value) is str and re.fullmatch(pattern, value) is not None


def manual_mutation(method, path, body):
    """Admit only bounded explicit manual bodies to this run's one private store."""
    if method != 'POST' or type(body) is not dict:
        return False
    key = body.get('idempotency_key')
    if path == '/api/editor/save':
        return (set(body) == {'idempotency_key', 'yaml_text', 'document_id', 'expected_source_hash'}
                and matches(key, r'[A-Za-z0-9_-]{1,128}')
                and type(body['yaml_text']) is str and 0 < len(body['yaml_text'].encode()) <= 262144
                and matches(body['document_id'], r'[a-f0-9]{32}')
                and matches(body['expected_source_hash'], r'[a-f0-9]{64}'))
    if path != VERSION_PATH or set(body) != {'idempotency_key', 'family', 'source', 'parent_revision_id'}:
        return False
    source = body['source']
    return (matches(key, r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}') and body['family'] == FAMILY
            and (body['parent_revision_id'] is None or matches(body['parent_revision_id'], r'[a-f0-9]{32}'))
            and type(source) is dict
            and set(source) == {'kind', 'editor_revision_id', 'source_hash', 'canonical_hash'}
            and source['kind'] == 'editor_revision'
            and matches(source['editor_revision_id'], r'[a-f0-9]{32}')
            and all(matches(source[k], r'[a-f0-9]{64}') for k in ('source_hash', 'canonical_hash')))
