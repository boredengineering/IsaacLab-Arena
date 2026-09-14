# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Independently read stopped API journal and artifacts from a read-only volume."""
import hashlib
import json
import os
import sqlite3
from pathlib import Path

BASE = Path('/acceptance')
assert os.getuid() != 0
browser = json.loads((BASE / 'browser-proof.json').read_text())
assert browser['status'] == 'passed'
assert json.loads((BASE / 'api-cleanup.json').read_text()) == {'lifespan_closed': True}
assert json.loads((BASE / 'socket-cleanup.json').read_text()) == {'socket_absent': True}
assert not (BASE / 'ipc/api.sock').exists()
closing = json.loads((BASE / 'api-before-cleanup.json').read_text())
assert closing['pending_workers'] == []
assert closing['publication_grants'] == 0
assert closing['publication_enabled'] is True and closing['publication_scheduler'] is True
assert closing['publication_admitting'] is True
assert closing['publication_workers'] == closing['publication_slots'] == closing['publication_tasks'] == 0
assert closing['publication_calls'] == {'accept': 0, 'enqueue': 0, 'issue_grant': 0}
bootstrap = json.loads((BASE / 'bootstrap.json').read_text())
assert bootstrap['fresh_private_only'] and bootstrap['before_enabled_lifespan'] and bootstrap['worker_support_ready']
journal = Path('/private/state/journal.sqlite3')
original = journal.read_bytes()
db = sqlite3.connect(f'file:{journal}?mode=ro&immutable=1', uri=True)
db.row_factory = sqlite3.Row
assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
publication_counts = {table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                      for table in ('publication_states', 'publication_bindings', 'publication_receipts',
                                    'publication_requests', 'publication_workers')}
assert all(count == 0 for count in publication_counts.values()), publication_counts
intents = [json.loads(row[0]) for row in db.execute('SELECT body FROM research_publication_intents')]
assert len(intents) == 1 and intents[0]['state'] == 'pending'
binding = browser['preparation_binding']
assert binding['registryId'] == bootstrap['registry_id']
assert binding['registryId'] == db.execute('SELECT registry_id FROM publication_worker_meta').fetchone()[0]
intent = intents[0]
assert intent['effect_id'] == binding['effectId']
assert intent['target_profile'] == binding['target']
assert intent['reservation_id'] == binding['versionRef']['reservation_id']
assert intent['payload_sha256'] == binding['versionRef']['payload_sha256']
prepared = next(c for c in browser['commits'] if c['publication_intent_id'])
projection = json.loads((Path('/private/managed') / prepared['relative_directory'] / 'projection.json').read_text())
assert binding['versionRef']['projection_digest'] == projection['digest']
assert binding['versionRef']['scope_id'] == projection['scope_id']
assert binding['versionRef']['canonical_identity'] == projection['canonical_identity']
assert (BASE / 'controls-before.yaml').read_bytes() == (BASE / 'controls-after.yaml').read_bytes()
assert browser['counters']['publication_posts'] == 0
assert db.execute("SELECT value FROM metadata WHERE key='clean_shutdown'").fetchone()[0] == 1
jobs = {row['id']: json.loads(row['body']) for row in db.execute('SELECT id,body FROM jobs')}
assert set(jobs) == {job['id'] for job in browser['jobs']}
for job in browser['jobs']:
    saved = jobs[job['id']]
    assert saved['status'] == 'succeeded'
    assert saved['result'] == job['result']
workers = [dict(row) for row in db.execute('SELECT * FROM workers')]
assert len(workers) == 2 and all(row['cleaned'] for row in workers)
attempts = [dict(row) for row in db.execute('SELECT * FROM attempts')]
assert len(attempts) == 2
artifacts = []
for commit in browser['commits']:
    reservation = commit['reservation']
    directory = Path('/private/managed') / commit['relative_directory']
    assert directory.is_relative_to('/private/managed')
    for name, expected in commit['manifest']['files'].items():
        file = directory / name
        data = file.read_bytes()
        actual = {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
        assert actual == expected, (name, actual, expected)
        artifacts.append({'reservation_id': reservation['reservation_id'], 'file': name, **actual})
    assert json.loads((directory / 'manifest.json').read_text()) == commit['manifest']
    source = reservation['source']
    row = db.execute('SELECT * FROM modern_candidate_receipts WHERE job_id=? AND attempt_id=? AND generation=?',
                     (source['job_id'], source['attempt_id'], source['generation'])).fetchone()
    assert row is not None
    assert hashlib.sha256(row['body'].encode()).hexdigest() == source['receipt_sha256']
events = [json.loads(row[0]) for row in db.execute('SELECT body FROM events ORDER BY id')]
assert events
assert journal.read_bytes() == original
assert not (BASE / 'forbidden-network.jsonl').exists()
proof = {'status': 'passed', 'journal_integrity': 'ok', 'clean_shutdown': True,
         'journal_sha256': hashlib.sha256(original).hexdigest(), 'read_only_journal_unchanged': True,
         'jobs': list(jobs), 'workers': workers, 'attempts': attempts, 'event_count': len(events),
         'artifacts': artifacts, 'publication_execution': False, 'publication_admission': True,
         'publication_table_counts': publication_counts, 'prepared_intents': intents,
         'publication_calls': closing['publication_calls'],
         'mounted_binding_matches_disk': True, 'editor_yaml_unchanged': True}
(BASE / 'disk-proof.json').write_text(json.dumps(proof, indent=2))
print(json.dumps(proof))
