#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Reviewed isolated native-storage probe; incomplete coverage remains PARTIAL."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

STOPPED_FRONTEND = '964ddf2e645854708368230ff1770495df6f94c2ecca22b17c7d01ebc611f97d'
PLAYWRIGHT_IMAGE = 'mcr.microsoft.com/playwright:v1.58.2-noble'
PLAYWRIGHT_ID = 'sha256:6446946a1d9fd62d9ae501312a2d76a43ee688542b21622056a372959b65d63d'
REVIEWED_BROWSER = True  # Parent enabled bounded PARTIAL smoke after deleg_ae004724; not full acceptance.
BROWSER_ENTRY = "import {runNativeStorageProbe,probeExit} from '/app/tests/e2e/functional-v7/ui-storage-browser.mjs'; process.exitCode=probeExit(await runNativeStorageProbe());"
EXEC_ENV = ['/usr/bin/env', '-i', 'HOME=/tmp', 'PATH=/usr/local/bin:/usr/bin:/bin',
            'PLAYWRIGHT_BROWSERS_PATH=/ms-playwright', 'NPM_CONFIG_OFFLINE=true',
            'NPM_CONFIG_IGNORE_SCRIPTS=true', 'NPM_CONFIG_CACHE=/tmp/npm-cache']
FIXTURE_ENTRY = 'tests/e2e/functional-v7/ui-storage-fixture.tsx'
FIXTURE_FILES = ('ui-storage-fixture.tsx', 'ui-storage-browser.mjs', 'ui-storage-fixture-loader.mjs',
                 'ui_storage_probe.py', 'run.py', 'confined_io.py', 'frontend_checks.py', 'check_proof.py')
MAX_FIXTURE_BYTES = 256 * 1024
MAX_EXEC_CAPTURE_BYTES = 1024 * 1024  # stdout + stderr per invocation, not an artifact disk quota.
REQUIRED_CASES = (
    'two-pages-concurrent-pins', 'competing-pins-at-capacity', 'legacy-exact-unchanged',
    'commit-notification-failure', 'request-success-then-abort', 'blocked-open-late-success',
    'versionchange', 'missing-record', 'notification-no-authority',
)


def gate_record():
    return {'schema_version': 1, 'profile': 'native-ui-storage-probe-v1', 'status': 'NOT-RUN',
            'reason': 'Parent safety review and production preference interface/case wiring pending.',
            'browser_approval': False, 'fixture_entry': FIXTURE_ENTRY,
            'real_api_evidence': False, 'required_cases': {case: 'NOT-RUN' for case in REQUIRED_CASES}}


def capture_fixture(here):
    """Capture exact test-only files through F0 no-follow bounded reads."""
    from confined_io import ConfinedRoot
    with ConfinedRoot(here) as source:
        captured = {name: source.read(name) for name in FIXTURE_FILES}
    assert sum(map(len, captured.values())) <= MAX_FIXTURE_BYTES, 'fixture aggregate budget'
    assert all(captured.values()), 'empty fixture'
    return captured


def stage_browser(frontend_root, destination):
    """Prepare frozen source, not execution; callable only after parent review."""
    from confined_io import ConfinedRoot
    from frontend_checks import capture
    # Reuse approved frontend source capture and its nested empty deps mountpoint.
    manifest = capture(frontend_root, destination)
    here = Path(frontend_root) / 'tests/e2e/functional-v7'
    captured = capture_fixture(here)
    with ConfinedRoot(destination) as target:
        for name, data in captured.items():
            relative = 'tests/e2e/functional-v7/' + name
            target.write_new(relative, data)
            manifest[relative] = hashlib.sha256(data).hexdigest()
    return manifest


def safeunits(selector):
    """Restore all process-global hooks, including admission/bootstrap failures."""
    import self_test
    import run
    sources, bootstrap = self_test.UNIT_SOURCES, self_test.NODE_UNITS
    docker, owned, argv = run.docker, run.OwnedRun, sys.argv
    try:
        return _safeunits(selector)
    finally:
        self_test.UNIT_SOURCES, self_test.NODE_UNITS = sources, bootstrap
        run.docker, run.OwnedRun, sys.argv = docker, owned, argv


def _safeunits(selector):
    """Extend only this process's existing F0 unit allowlists; no new Docker path."""
    assert selector == STOPPED_FRONTEND, 'exact approved stopped frontend ID required'
    import self_test
    # Keep original suite constants intact; the fresh sandbox entry selects this
    # additive suite locally, leaving existing F0 contract tests unchanged.
    self_test.UNIT_SOURCES = (*self_test.UNIT_SOURCES, 'ui_storage_probe.py', 'test_ui_storage_probe.py',
                             'ui-storage-probe.test.mjs', *FIXTURE_FILES)
    old = "files:['/source/request-correlation.test.mjs', '/source/manual-research.test.mjs']"
    assert self_test.NODE_UNITS.count(old) == 1, 'approved unit bootstrap changed; review required'
    self_test.NODE_UNITS = self_test.NODE_UNITS.replace(old,
        "files:['/source/request-correlation.test.mjs', '/source/manual-research.test.mjs', '/source/ui-storage-probe.test.mjs']")
    # Preserve actual Docker wait status in ownership/run proof, including failures,
    # without replacing discovery/creation/isolation/cleanup implementations.
    import run
    original_docker, original_owned = run.docker, run.OwnedRun
    active = []
    def recorded_docker(*args):
        try:
            value = original_docker(*args)
        except BaseException as error:
            if args[0] == 'wait' and active:
                active[0].proof.setdefault('unit_exits', []).append({'id': args[1], 'exit': None, 'error': type(error).__name__})
            raise
        if args[0] == 'wait' and active:
            active[0].proof.setdefault('unit_exits', []).append({'id': args[1], 'exit': value})
        return value
    class UnitRun(original_owned):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.proof['browser_gate'] = gate_record()
            active.append(self)

        def create(self, role, image, entrypoint, args, mounts):
            if role == 'tests':
                assert args[-2:] == ['/source/self_test.py', '--inside'], 'approved Python unit entry changed'
                args = [*args[:-2], '/source/ui_storage_probe.py', '--inside']
                self.proof['unit_entry'] = args
            return super().create(role, image, entrypoint, args, mounts)

        def cleanup(self):
            clean = super().cleanup()  # Never skip owned cleanup on metadata failure.
            try:
                discovery = self.proof.get('discovery', {})
                after = run.discover_frontend(Path(__file__).resolve().parents[5], selector)
                self.proof['frontend_dependency_after'] = after
                assert after['frontend_dependency_origin'] == discovery['frontend_dependency_origin'], 'stopped dependency metadata changed'
                assert after['deps'] == discovery['deps'], 'dependency volume changed'
                self.proof['stopped_frontend_unchanged'] = True
            except BaseException as error:
                self.proof['stopped_frontend_unchanged'] = False
                self.proof.setdefault('cleanup_errors', []).append('dependency readback: ' + type(error).__name__ + ': ' + str(error))
                clean = False
            return clean
    previous = sys.argv
    try:
        run.docker, run.OwnedRun = recorded_docker, UnitRun
        sys.argv = [str(Path(__file__).with_name('self_test.py')), '--node-units',
                    '--frontend-dependency-container', selector]
        return self_test.main()
    finally:
        sys.argv = previous
        run.docker, run.OwnedRun = original_docker, original_owned


class CaptureFailure(RuntimeError):
    """Static failure code with bounded raw partial output and CLI reap status."""
    def __init__(self, reason, stdout=b'', stderr=b'', client_cleaned=True):
        super().__init__(reason)
        self.reason, self.stdout, self.stderr = reason, stdout, stderr
        self.client_cleaned = client_cleaned


def capture_exec(argv, timeout):
    """Stream a fixed Docker exec client under a combined byte/deadline budget.

    Kill/reap only the retained direct Popen child, never a numeric process group.
    Container descendants remain OwnedRun's responsibility on every outcome.
    This does not bound child-written evidence, Docker logs, or metadata capture.
    """
    import os
    import selectors
    import subprocess
    import time
    deadline = time.monotonic() + timeout
    captured = {'stdout': bytearray(), 'stderr': bytearray()}
    total, reason, client_cleaned = 0, None, True
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, bufsize=0, close_fds=True)
    except BaseException:
        # A constructor exception provides no retained child/reap witness.
        raise CaptureFailure('spawn-error', client_cleaned=False) from None
    try:
        with selectors.DefaultSelector() as ready:
            for key in captured:
                stream = getattr(process, key)
                os.set_blocking(stream.fileno(), False)
                ready.register(stream, selectors.EVENT_READ, key)
            while ready.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                for event, unused in ready.select(remaining):
                    # Read at most one overflow witness beyond the retained cap.
                    allowance = MAX_EXEC_CAPTURE_BYTES - total
                    chunk = os.read(event.fd, min(65536, allowance + 1))
                    if not chunk:
                        ready.unregister(event.fileobj)
                        continue
                    captured[event.data].extend(chunk[:allowance])
                    total += min(len(chunk), allowance)
                    if len(chunk) > allowance:
                        raise OverflowError
            returncode = process.wait(timeout=max(0, deadline - time.monotonic()))
    except BaseException as error:
        reason = ('timeout' if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)) else
                  'overflow' if isinstance(error, OverflowError) else
                  'interrupted' if isinstance(error, (KeyboardInterrupt, InterruptedError)) else 'capture-error')
        # Popen owns the unreaped child identity. Closing the client alone cannot
        # stop docker-exec descendants; the outer finally MUST still remove CID.
        try:
            if process.returncode is None:
                process.kill()
        except BaseException:
            client_cleaned = False
        try:
            process.wait(timeout=5)
        except BaseException:
            client_cleaned = False
    finally:
        for key in captured:
            try:
                getattr(process, key).close()
            except BaseException:
                reason = reason or 'capture-error'
                client_cleaned = False
    stdout, stderr = bytes(captured['stdout']), bytes(captured['stderr'])
    if reason:
        raise CaptureFailure(reason, stdout, stderr, client_cleaned) from None
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def browser_lifecycle(root, output, selector):
    """Run the fixed owned lifecycle; admission is exclusively the locked CLI."""
    import os
    import signal
    import uuid
    from confined_io import ConfinedRoot, read_confined
    from frontend_checks import PROBE
    from run import OwnedRun, compare_source, discover_frontend, docker, hash_evidence, image_metadata, verify_container
    assert selector == STOPPED_FRONTEND, 'exact approved stopped frontend ID required'
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    assert not any(output.iterdir()), 'fresh output required'
    owned = OwnedRun(output, 'arena-storage-' + uuid.uuid4().hex[:12])
    proof = owned.proof
    proof.update(status='failed', profile='native-ui-storage-host-v1', real_api_evidence=False,
                 dependency_selector=selector, executions=[], evidence_errors=[], cleanup_verified=False,
                 required_cases={name: 'NOT-RUN' for name in REQUIRED_CASES})
    previous = {}
    def interrupted(signum, frame):
        raise InterruptedError('signal ' + str(signum))
    def execute(role, cid, args, timeout):
        argv = ['docker', 'exec', '--user', '1000:1000', '-w', '/app', cid, *EXEC_ENV, *args]
        row = {'role': role, 'argv': argv, 'container_id': cid, 'image_id': PLAYWRIGHT_ID,
               'source_manifest_sha256': hashlib.sha256(read_confined(output, 'source-manifest.json')).hexdigest(),
               'dependency_selector': selector, 'exit_code': None, 'sequence': len(proof['executions']),
               'capture_limit_bytes': MAX_EXEC_CAPTURE_BYTES, 'capture_status': 'incomplete',
               'client_cleanup_verified': False,
               'stdout': 'host-capture/' + role + '.stdout', 'stderr': 'host-capture/' + role + '.stderr'}
        proof['executions'].append(row)
        owned.save()  # An incomplete invocation must remain visible.
        captured = {'stdout': b'', 'stderr': b''}
        try:
            result = capture_exec(argv, timeout=timeout)
            row['exit_code'] = result.returncode
            row.update(capture_status='complete', client_cleanup_verified=True)
            captured = {'stdout': result.stdout, 'stderr': result.stderr}
            return result
        except CaptureFailure as error:
            row.update(error='CaptureFailure: ' + error.reason, capture_status=error.reason,
                       client_cleanup_verified=error.client_cleaned)
            captured = {'stdout': error.stdout, 'stderr': error.stderr}
            raise
        except BaseException as error:
            row['error'] = type(error).__name__
            raise
        finally:
            try:
                with ConfinedRoot(output / 'host-capture') as capture:
                    for key, raw in captured.items():
                        capture.write_new(role + '.' + key, raw)
            finally:
                owned.save()  # Never roll back/reopen a path after a write error.
    try:
        # This sibling is host-owned and NEVER mounted. Child evidence is read
        # only by confined readers; success/error paths never write below it.
        with ConfinedRoot(output) as parent:
            os.mkdir('host-capture', mode=0o700, dir_fd=parent.fd)
        (output / 'evidence').mkdir(mode=0o700)
        os.chown(output / 'evidence', 1000, 1000)
        owned.save()
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, interrupted)
        discovery = discover_frontend(root, frontend_dependency_container=selector)
        proof['discovery'] = discovery
        manifest = stage_browser(root / 'web/arena-workbench', output / 'source')
        proof['source_sha256'] = manifest
        (output / 'source-manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2))
        proof['image_projection'] = image_metadata(PLAYWRIGHT_ID)
        assert proof['image_projection']['Id'] == PLAYWRIGHT_ID, 'immutable image mismatch'
        host = discovery['host_root'] + '/' + output.relative_to(root).as_posix()
        proof['host_output'] = host
        mounts = [f'type=bind,src={host}/source,dst=/app,readonly',
                  f'type=volume,src={discovery["deps"]},dst=/app/node_modules,readonly',
                  f'type=bind,src={host}/evidence,dst=/evidence']
        cid = owned.create('storage', PLAYWRIGHT_ID, '/usr/bin/env',
                           ['-i', 'HOME=/tmp', 'PATH=/usr/local/bin:/usr/bin:/bin', 'sleep', '360'], mounts)
        verify_container(owned, cid, mounts)
        assert owned.proof['containers'][-1]['image'] == PLAYWRIGHT_ID, 'inspected runtime image mismatch'
        docker('start', cid)
        preimport = execute('dependency-preflight', cid, ['node', '-e', PROBE], 45)
        assert type(preimport.returncode) is int and preimport.returncode == 0, 'dependency preflight exec failed'
        receipt = json.loads(read_confined(output, 'evidence/preimport-frontend.json'))
        assert json.dumps(json.loads(preimport.stdout), sort_keys=True) == json.dumps(receipt, sort_keys=True), 'preflight stdout/readback mismatch'
        assert receipt['status'] == 'passed' and receipt['before_repository_imports'] is True
        assert receipt['egress_denied'] is True and type(receipt['uid']) is int and receipt['uid'] == 1000
        proof['preimport'] = receipt
        owned.save()
        result = execute('storage-driver', cid, ['node', '--input-type=module', '-e', BROWSER_ENTRY], 240)
        driver = json.loads(read_confined(output, 'evidence/storage-browser.json'))
        proof['browser_status'] = driver['status']
        assert driver['cleanup_verified'] is True and driver['errors'] == [], 'driver failure/cleanup'
        assert type(result.returncode) is int and result.returncode == 2 and driver['status'] == 'PARTIAL', 'driver exec failed or unsupported full native acceptance'
        proof['status'] = 'PARTIAL'
        proof['required_cases'] = driver.get('required_cases', proof['required_cases'])
    except BaseException as error:
        proof['failure'] = type(error).__name__ + ': ' + str(error)[:2048]
        proof['status'] = 'failed'
    finally:
        for signum in previous:
            signal.signal(signum, signal.SIG_IGN)
        try:
            try:
                proof['cleanup_verified'] = owned.cleanup() is True
            except BaseException as error:
                proof['remaining_owned'] = None
                proof.setdefault('cleanup_errors', []).append(str(error)[:2048])
            try:
                if 'discovery' in proof:
                    after = discover_frontend(root, frontend_dependency_container=selector)
                    proof['frontend_dependency_after'] = after
                    assert after == proof['discovery'], 'stopped dependency metadata changed'
                    proof['stopped_frontend_unchanged'] = True
            except BaseException as error:
                proof['evidence_errors'].append('dependency readback: ' + str(error)[:2048])
            try:
                manifest = proof.get('source_sha256', {})
                changed, rejected = compare_source(output / 'source', manifest) if manifest else ([], [])
                proof['staged_source_unchanged'] = bool(manifest) and not changed and not rejected
                proof['evidence_errors'].extend(changed + rejected)
                proof['artifacts'] = {}
                if (output / 'evidence').is_dir():
                    hash_evidence(output, proof['artifacts'], proof['evidence_errors'])
                for execution in proof['executions']:
                    for key in ('stdout', 'stderr'):
                        name = execution[key]
                        proof['artifacts'][name] = hashlib.sha256(read_confined(output, name)).hexdigest()
                if manifest:
                    proof['artifacts']['source-manifest.json'] = hashlib.sha256(read_confined(output, 'source-manifest.json')).hexdigest()
            except BaseException as error:
                proof['evidence_errors'].append('hash finalization: ' + str(error)[:2048])
            if not proof['cleanup_verified'] or not proof.get('staged_source_unchanged') or proof['evidence_errors']:
                proof['status'] = 'failed'
            owned.save()  # Freeze ownership before hashing; never save it again.
            proof.setdefault('artifacts', {})['ownership.json'] = hashlib.sha256(read_confined(output, 'ownership.json')).hexdigest()
            (output / 'run-proof.json').write_text(json.dumps(proof, indent=2))
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    print(json.dumps({'output': str(output), 'status': proof['status'], 'remaining_owned': proof.get('remaining_owned')}))
    return {'passed': 0, 'PARTIAL': 2}.get(proof['status'], 1)


def validate_native_cases(cases):
    """Independently validate candidate observations, not execution authenticity."""
    try:
        return _validate_native_cases(cases)
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise AssertionError('native case witness missing/malformed') from error


def _validate_native_cases(cases):
    from check_proof import parse
    encode = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    same = lambda left, right: encode(left) == encode(right)
    integer = lambda value: type(value) is int and 0 <= value <= 9007199254740991
    refs = [{'id': 'editor-revision:' + digit * 32, 'kind': 'editor_revision', 'revision_id': digit * 32,
             'source_hash': digit * 64, 'canonical_hash': 'a' * 64} for digit in '123456789']
    hint = 'library-preferences-changed/v1'
    def record(observation, pins, revision, recents=()):
        assert set(observation) == {'state', 'raw', 'settledBy', 'binding'}, 'native durable observation fields'
        assert observation['settledBy'] == 'transaction.oncomplete', 'native durable completion'
        assert observation['state'] == 'record' and type(observation['raw']) is str and len(observation['raw']) <= 32768, 'native durable record'
        value = parse(observation['raw'])
        expected = {'schemaVersion': 1, 'revision': revision, 'preferences': {'version': 1, 'pins': pins, 'recents': list(recents)}}
        assert same(value, expected), 'native exact durable identity/revision'
        return value
    def absent(observation):
        assert same({k: v for k, v in observation.items() if k != 'binding'}, {'state': 'absent-record', 'raw': None, 'settledBy': 'transaction.oncomplete'}), 'native deleted record witness'
    def selected(audit, kind, **fields):
        return [event for event in audit['events'] if event['type'] == kind and all(same(event.get(k), v) for k, v in fields.items())]
    def one(audit, kind, **fields):
        values = selected(audit, kind, **fields)
        assert len(values) == 1, 'native unique witness: ' + kind
        return values[0]
    def ordered(audit, *kinds, **fields):
        events = [one(audit, kind, **fields) for kind in kinds]
        assert [e['seq'] for e in events] == sorted(e['seq'] for e in events), 'native witness order'
        return events
    def prefix(cut, final):
        assert cut['overflow'] is False and same(cut['events'], final['events'][:len(cut['events'])]), 'native witness prefix'
    def audit_valid(audit):
        assert set(audit) == {'events', 'overflow', 'snapshot'} and audit['overflow'] is False, 'native audit overflow/schema'
        events = audit['events']
        assert type(events) is list and 0 < len(events) <= 512, 'native event budget'
        assert all(type(e['seq']) is int and e['seq'] == index + 1 and type(e['type']) is str for index, e in enumerate(events)), 'native event sequence'
        assert not any(e['type'] in ('barrier-deadline', 'barrier-budget', 'barrier-abort', 'operation-deadline') for e in events), 'native bounded barrier failed'
        created = {}
        connections = {}
        terminals = set()
        for event in events:
            if event['type'] in ('transaction-created', 'transaction-complete', 'transaction-abort', 'get-success', 'put-success', 'delete-success', 'abort-after-put-success'):
                assert 'tx' in event, 'native orphan transaction event'
            if event['type'] == 'transaction-created':
                tx = event['tx']
                assert integer(tx) and tx > 0 and tx not in created and integer(event['connection']) and event['connection'] > 0, 'native transaction identity'
                assert event['mode'] in ('readonly', 'readwrite'), 'native transaction mode'
                assert event['role'] in ('production', 'fixture', 'observer'), 'native connection role'
                assert connections.setdefault(event['connection'], event['role']) == event['role'], 'native connection role changed'
                assert event['role'] != 'observer' or event['mode'] == 'readonly', 'native observer cannot write'
                created[tx] = event
            elif 'tx' in event:
                tx = event['tx']
                assert tx in created and tx not in terminals, 'native transaction lifecycle'
                assert all(event[k] == created[tx][k] for k in ('connection', 'label', 'mode', 'role')), 'native transaction binding'
                if event['type'] == 'transaction-abort':
                    intentional = ((name == 'request-success-then-abort' and event['label'] == 'command' and event['mode'] == 'readwrite') or
                                   (name == 'missing-record' and event['label'] == 'refresh' and event['mode'] == 'readonly'))
                    assert intentional and event['role'] == 'production', 'native unexpected transaction abort'
                if event['type'] in ('transaction-complete', 'transaction-abort'): terminals.add(tx)
        for tx, event in created.items():
            if event['mode'] == 'readwrite':
                assert tx in terminals, 'native awaited write terminal missing'
                if event['label'] == 'seed':
                    ordered(audit, 'transaction-created', 'put-success', 'transaction-complete', tx=tx)
        # A final sample can still have a queued readonly notification; closure
        # and explicit observer bindings impose their additional requirements.
        modes = [e['mode'] for e in events if e['type'] == 'snapshot']
        if 'memory' in modes:
            assert all(mode == 'memory' for mode in modes[modes.index('memory'):]), 'native fallback reactivation'
    def bound(observation, audit):
        binding = observation['binding']
        assert set(binding) == {'connection', 'tx', 'created', 'get', 'complete'} and all(integer(v) and v > 0 for v in binding.values()), 'native readback binding fields'
        chain = ordered(audit, 'transaction-created', 'get-success', 'transaction-complete', tx=binding['tx'])
        assert [e['seq'] for e in chain] == [binding[k] for k in ('created', 'get', 'complete')], 'native readback event identities'
        assert all(e['connection'] == binding['connection'] and e['role'] == 'observer' and e['mode'] == 'readonly' for e in chain), 'native independent observer binding'
        assert chain[1]['raw'] == observation['raw'], 'native readback raw event binding'
        return binding
    def barrier(row, cut_name):
        final, cut = row['audits'][0], row[cut_name]
        if type(cut) is list: cut = cut[0]
        prefix(cut, final)
        tx = one(cut, 'transaction-created', label='barrier', mode='readwrite')['tx']
        one(cut, 'barrier-active')
        assert not selected(cut, 'barrier-release') and not selected(cut, 'transaction-complete', tx=tx), 'native barrier not held'
        release = one(final, 'barrier-release'); complete = one(final, 'barrier-complete')
        assert integer(release['count']) and 1 <= release['count'] <= complete['count'] <= 100000, 'native barrier keepalive bound'
        assert release['seq'] < one(final, 'transaction-complete', tx=tx)['seq'] < complete['seq'], 'native barrier completion order'
    assert type(cases) is dict and set(cases) == set(REQUIRED_CASES), 'native case set'
    for name, row in cases.items():
        assert row['id'] == name and type(row['schema']) is int and row['schema'] == 2 and row['status'] == 'observed', 'native case identity/status'
        assert row['isolation'] == 'fresh-browser-context' and row['initial'] == {'state': 'absent-database'}, 'native fresh context'
        assert row['scope'] == 'native production controller; synthetic editor references/admission; no API/source authority', 'native scope'
        assert type(row['browser_version']) is str and row['browser_version'], 'native browser metadata'
        assert same(row['bounds'], {'barrier_ms': 4000, 'barrier_requests': 100000, 'events_per_page': 512}), 'native bounds'
        assert row['cleanup_verified'] is True and not row.get('error') and not row.get('cleanup_error'), 'native case cleanup/error'
        parallel = name in ('two-pages-concurrent-pins', 'competing-pins-at-capacity')
        pages = 2 if parallel or name == 'notification-no-authority' else 1
        assert len(row['audits']) == len(row['closed']) == pages, 'native page evidence count'
        for a, closed in zip(row['audits'], row['closed']):
            audit_valid(a); audit_valid(closed); prefix(a, closed)
            assert one(closed, 'fixture-closed')['seq'] == len(closed['events']), 'native events after closure'
            for event in closed['events'][len(a['events']):-1]:
                assert event['type'] == 'connection-close' or (event['type'] in (
                    'transaction-created', 'get-success', 'transaction-complete', 'transaction-abort'
                ) and event.get('mode') == 'readonly'), 'native cleanup mutation/notification'
            created = selected(closed, 'transaction-created')
            for event in created:
                terminals = selected(closed, 'transaction-complete', tx=event['tx']) + selected(closed, 'transaction-abort', tx=event['tx'])
                assert len(terminals) == 1, 'native closed transaction terminal missing'
        # All outcome/no-extra-write/no-notification semantics see the closed
        # trace, never just the convenient pre-cleanup sample.
        row = dict(row, audits=row['closed'])
        a = row['audits'][0]
        expected_writes = {
            'two-pages-concurrent-pins': [3, 2], 'competing-pins-at-capacity': [4, 2],
            'legacy-exact-unchanged': [1], 'commit-notification-failure': [2],
            'request-success-then-abort': [2], 'blocked-open-late-success': [1],
            'versionchange': [1], 'missing-record': [2], 'notification-no-authority': [2, 1],
        }[name]
        for page, (final, expected_count) in enumerate(zip(row['audits'], expected_writes)):
            assert len(selected(final, 'transaction-created', mode='readwrite')) == expected_count, 'native unexpected write transaction/replay'
            assert len(selected(final, 'transaction-created', mode='readonly')) <= 12, 'native readonly transaction bound'
            initializations = [e for e in selected(final, 'transaction-created', mode='readwrite') if e['label'] in ('initialize', 'fixture')]
            assert len(initializations) == (0 if name == 'blocked-open-late-success' else 1), 'native initialization count'
            for initialized in initializations:
                assert initialized['role'] == 'production', 'native initialization production connection'
                chain = ordered(final, 'transaction-created', 'get-success', 'transaction-complete', tx=initialized['tx'])
                puts = selected(final, 'put-success', tx=initialized['tx'])
                expected_puts = 0 if name == 'competing-pins-at-capacity' or page == 1 else 1
                assert len(puts) == expected_puts, 'native initialization extra/missing put'
                if puts: assert chain[1]['seq'] < puts[0]['seq'] < chain[-1]['seq'], 'native initialization put order'
            for event in selected(final, 'transaction-created', mode='readwrite'):
                assert event['label'] in ('initialize', 'fixture', 'seed', 'command', 'barrier', 'delete-record'), 'native unexpected write purpose'
                if event['label'] in ('barrier', 'delete-record'):
                    assert event['role'] == 'fixture' and not selected(final, 'put-success', tx=event['tx']), 'native fixture unexpected put'
            deletes = selected(final, 'delete-success')
            assert len(deletes) == (1 if name == 'missing-record' else 0), 'native delete request witness'
            if deletes:
                assert deletes[0]['label'] == 'delete-record' and deletes[0]['role'] == 'fixture' and deletes[0]['mode'] == 'readwrite', 'native delete purpose'
                assert deletes[0]['key'] == 'default' and deletes[0]['store'] == 'libraryPreferences', 'native delete key/store'
                ordered(final, 'transaction-created', 'delete-success', 'transaction-complete', tx=deletes[0]['tx'])
        before, after = row['before'], row['after']
        for page, final in enumerate(row['audits']):
            observations = ([row['uiRecord']] if page == 1 and name == 'notification-no-authority' else
                            ([before[page]] if before else []) +
                            ([row['deleted']] if name == 'missing-record' else []) + [after[page]])
            bindings = [bound(o, final) for o in observations]
            assert len({b['tx'] for b in bindings}) == len(bindings), 'native reused observer readback'
            assert [b['created'] for b in bindings] == sorted(b['created'] for b in bindings), 'native readback temporal order'
            assert {b['tx'] for b in bindings} == {e['tx'] for e in selected(final, 'transaction-created', role='observer')}, 'native orphan observer transaction'
            starts = selected(final, 'command-start')
            ends = selected(final, 'command-outcome')
            if starts:
                assert bindings[0]['complete'] < starts[0]['seq'], 'native before readback after command'
                assert ends[-1]['seq'] < bindings[-1]['created'], 'native after readback before outcome'
        assert len(after) == (2 if parallel else 1) and len(before) == (0 if name == 'legacy-exact-unchanged' else 2 if parallel else 1), 'native readback count'
        if name == 'legacy-exact-unchanged':
            assert same(row['initWitness'], {'phase': 'playwright-init-script', 'readyState': 'loading', 'scripts': 0,
                        'fixturePresent': False, 'raw': row['legacyBefore'], 'verifiedRaw': row['legacyBefore']}), 'native pre-module seed witness'
            assert same(row['moduleEntry'], {'phase': 'fixture-module-entry', 'raw': row['legacyBefore'], 'initSeen': True}), 'native module entry seed witness'
            assert row['preMount'] == {'events': [], 'overflow': False, 'snapshot': None}, 'native migration before mount'
            assert type(row['legacyBefore']) is str and row['legacyBefore'] == row['legacyAfter'], 'native legacy unchanged bytes'
            expected = record(after[0], refs[:2], 0, refs[2:3])
            assert same(parse(row['legacyBefore']), expected['preferences']), 'native migrated exact preferences'
            tx = one(a, 'transaction-created', label='initialize', mode='readwrite')['tx']
            ordered(a, 'get-success', 'put-success', 'transaction-complete', tx=tx)
            assert a['snapshot']['mode'] == 'persistent' and same(a['snapshot']['preferences'], expected['preferences']), 'native migrated snapshot'
            continue
        if name in ('competing-pins-at-capacity', 'blocked-open-late-success'):
            seed = one(a, 'transaction-created', label='seed', mode='readwrite', role='fixture')
            seed_put = one(a, 'put-success', tx=seed['tx'])
            assert same(parse(seed_put['raw']), parse(before[0]['raw'])), 'native seed exact raw binding'
            assert one(a, 'transaction-complete', tx=seed['tx'])['seq'] < before[0]['binding']['created'], 'native completed seed before readback'
        initial_pins = refs[:7] if name == 'competing-pins-at-capacity' else []
        for observation in before: record(observation, initial_pins, 0)
        if parallel:
            assert row['schedule'] == 'two native command transactions queued behind active readwrite barrier; writes serialize, not simultaneous execution', 'native schedule disclosure'
            assert len(row['queued']) == 2, 'native queued pair'
            barrier(row, 'queued')
            capacity = name == 'competing-pins-at-capacity'
            assert sorted(row['outcomes']) == (['committed', 'limit'] if capacity else ['committed', 'committed']), 'native competing outcomes'
            pins = refs[:7] + [refs[7 + row['outcomes'].index('committed')]] if capacity else refs[:2]
            # Durable insertion order is the actual native transaction order. Either
            # contender can win scheduling; both exact identities must survive.
            for observation in after:
                actual = parse(observation['raw'])['preferences']['pins']
                assert sorted(map(encode, actual)) == sorted(map(encode, pins)), 'native exact competing pins'
                record(observation, actual, 1 if capacity else 2)
            assert after[0]['raw'] == after[1]['raw'], 'native independent same-origin readbacks'
            for index, (cut, final) in enumerate(zip(row['queued'], row['audits'])):
                prefix(cut, final)
                tx = one(cut, 'transaction-created', label='command', mode='readwrite')['tx']
                assert not any(e.get('tx') == tx and e['type'] != 'transaction-created' for e in cut['events']), 'native queued transaction executed before release'
                assert not selected(cut, 'command-outcome'), 'native queued command settled'
                ordered(final, 'transaction-created', 'get-success', 'transaction-complete', tx=tx)
                if index == 0:
                    assert one(final, 'barrier-complete')['seq'] < one(final, 'get-success', tx=tx)['seq'], 'native command ran before barrier completion'
                end = one(final, 'command-outcome', index=index + (7 if capacity else 0))
                assert end['outcome'] == row['outcomes'][index] and one(final, 'transaction-complete', tx=tx)['seq'] < end['seq'], 'native complete before outcome'
                puts = selected(final, 'put-success', tx=tx)
                posts = selected(final, 'notification-post', source='production')
                assert len(puts) == len(posts) == (1 if end['outcome'] == 'committed' else 0), 'native limit cannot write/notify'
                if posts:
                    assert one(final, 'transaction-complete', tx=tx)['seq'] < posts[0]['seq'] < end['seq'] and posts[0]['message'] == hint, 'native commit before notification'
                assert final['snapshot']['mode'] == 'persistent' and same(final['snapshot']['preferences'], parse(after[0]['raw'])['preferences']), 'native parallel snapshot'
            continue
        if name in ('commit-notification-failure', 'request-success-then-abort'):
            abort = name == 'request-success-then-abort'
            assert row['fault'] == ('native put success listener calls same transaction.abort before complete' if abort else 'BroadcastChannel.prototype.postMessage throws after native command transaction complete'), 'native fault disclosure'
            tx = one(a, 'transaction-created', label='command', mode='readwrite')['tx']
            ordered(a, 'transaction-created', 'get-success', 'put-success', 'transaction-abort' if abort else 'transaction-complete', tx=tx)
            end = one(a, 'command-outcome', index=0)
            assert row['outcomes'] == [end['outcome']] == (['unavailable'] if abort else ['committed']), 'native commit outcome'
            if abort:
                ordered(a, 'put-success', 'abort-after-put-success', 'transaction-abort', tx=tx)
                assert not selected(a, 'transaction-complete', tx=tx) and not selected(a, 'notification-post'), 'native abort cannot commit/notify'
                assert one(a, 'transaction-abort', tx=tx)['seq'] < end['seq'], 'native abort before outcome'
                record(after[0], [], 0)
                assert before[0]['raw'] == after[0]['raw'], 'native abort unchanged record'
                assert one(a, 'arm-abort')['seq'] < one(a, 'put-success', tx=tx)['seq'], 'native abort armed'
            else:
                assert one(a, 'transaction-complete', tx=tx)['seq'] < one(a, 'notification-post', source='production')['seq'] < one(a, 'notification-post-threw')['seq'] < end['seq'], 'native post fault after commit'
                assert one(a, 'arm-post-failure')['seq'] < one(a, 'transaction-created', tx=tx)['seq'], 'native post fault armed'
                assert not selected(a, 'transaction-abort', tx=tx), 'native committed cannot abort'
                record(after[0], refs[:1], 1)
                assert 'notification unavailable' in a['snapshot']['notice'], 'native notification failure notice'
            assert a['snapshot']['mode'] == ('memory' if abort else 'persistent'), 'native commit/abort mode'
            assert same(a['snapshot']['preferences'], parse(after[0]['raw'])['preferences']), 'native commit/abort snapshot'
            continue
        if name in ('blocked-open-late-success', 'versionchange', 'missing-record'):
            assert row['outcomes'] == ['memory'] and a['snapshot']['mode'] == 'memory', 'native terminal fallback'
            assert same(a['snapshot']['preferences'], {'version': 1, 'pins': refs[:1], 'recents': []}), 'native memory command not replayed'
            start = one(a, 'command-start', index=0)
            end = one(a, 'command-outcome', index=0, outcome='memory')
            fallback = selected(a, 'snapshot', mode='memory')[0]
            assert fallback['seq'] < start['seq'] < end['seq'], 'native fallback before memory command'
            assert not selected(a, 'transaction-created', label='command', mode='readwrite') and not selected(a, 'notification-post'), 'native fallback no writes/notification'
            if name == 'blocked-open-late-success':
                assert row['fault'] == 'bounded factory version fault: production requested v1, native request v2 behind held v1; late upgrade abort, NOT late success', 'native version fault disclosure'
                prefix(row['blocked'], a)
                assert one(a, 'open-blocked')['seq'] < fallback['seq'] <= len(row['blocked']['events']) < start['seq'] < end['seq'] < one(a, 'holder-released')['seq'], 'native blocked command release chain'
                ordered(a, 'factory-version-fault', 'holder-versionchange', 'open-blocked', 'holder-released', 'late-upgradeneeded', 'late-upgrade-abort', 'open-error')
                one(a, 'factory-version-fault', requested=1, actual=2)
                one(a, 'holder-versionchange', oldVersion=1, newVersion=2)
                one(a, 'open-error', name='AbortError')
                assert row['blocked']['snapshot']['mode'] == 'memory' and not selected(row['blocked'], 'holder-released'), 'native blocked fallback before release'
                assert not selected(a, 'open-success') and not selected(a, 'snapshot', mode='persistent'), 'native late open cannot reactivate'
                assert row['databases'] == [{'name': 'arena-workbench-ui', 'version': 1}], 'native aborted upgrade version'
            elif name == 'versionchange':
                prefix(row['retired'], a)
                assert len(row['retired']['events']) < start['seq'], 'native retirement before command'
                initialized = one(a, 'transaction-created', label='initialize', mode='readwrite', role='production')
                event = one(a, 'native-versionchange', oldVersion=1, newVersion=2)
                upgrade = one(a, 'independent-upgrade-complete', version=2)
                assert event['connection'] == initialized['connection'], 'native versionchange initialized connection'
                assert one(a, 'transaction-complete', tx=initialized['tx'])['seq'] < event['seq'] < upgrade['seq'] <= len(row['retired']['events']) < start['seq'], 'native versionchange upgrade retirement chain'
                assert selected(a, 'connection-close', connection=event['connection'], version=1), 'native old connection closed'
                assert row['retired']['snapshot']['mode'] == 'memory', 'native versionchange fallback'
                assert row['databases'] == [{'name': 'arena-workbench-ui', 'version': 2}], 'native independent upgrade version'
            else:
                absent(row['deleted']); absent(after[0])
                tx = one(a, 'transaction-created', label='delete-record', mode='readwrite')['tx']
                deleted_complete = one(a, 'transaction-complete', tx=tx)
                # Observer and refresh both use label refresh; only the production
                # refresh aborts on the missing record.
                aborted = one(a, 'transaction-abort', mode='readonly')
                assert aborted['label'] == 'refresh' and aborted['role'] == 'production', 'native missing record conflict'
                initialized = one(a, 'transaction-created', label='initialize', mode='readwrite', role='production')
                read_chain = ordered(a, 'transaction-created', 'get-success', 'transaction-abort',
                                     tx=aborted['tx'], connection=initialized['connection'], role='production', mode='readonly')
                assert read_chain[1]['raw'] is None, 'native production refresh observed absent record'
                assert deleted_complete['seq'] < row['deleted']['binding']['created'] < row['deleted']['binding']['complete'] < one(a, 'transaction-created', tx=aborted['tx'])['seq'] < aborted['seq'] < fallback['seq'] < start['seq'], 'native delete refresh fallback command chain'
                assert not selected(a, 'put-success', label='refresh'), 'native disappearance cannot reinitialize'
                continue
            record(after[0], [], 0)
            assert before[0]['raw'] == after[0]['raw'], 'native fallback durable unchanged'
            continue
        assert name == 'notification-no-authority', 'native unsupported case'
        expected_payloads = [{'revision': 999, 'preferences': {'pins': refs[:1]}}, {'type': hint, 'revision': 999}, 'foreign', None]
        assert same(row['payloads'], expected_payloads), 'native forged payload set'
        for key in ('beforeMessages', 'invalidDelivered', 'beforeHints', 'heldHints', 'afterHints'): prefix(row[key], a)
        before_messages, invalid, before_hints, held, finished = (row[key] for key in ('beforeMessages', 'invalidDelivered', 'beforeHints', 'heldHints', 'afterHints'))
        assert same(selected(before_messages, 'transaction-created'), selected(invalid, 'transaction-created')), 'native invalid message started transaction'
        assert same([e['data'] for e in selected(invalid, 'message-delivered')], expected_payloads), 'native invalid messages not delivered'
        barrier(row, 'heldHints')
        queued = [e for e in selected(held, 'transaction-created') if e['seq'] > len(before_hints['events'])]
        assert len(queued) == 1 and queued[0]['mode'] == 'readonly', 'native one coalesced queued refresh'
        assert not selected(held, 'get-success', tx=queued[0]['tx']) and not selected(held, 'transaction-complete', tx=queued[0]['tx']), 'native refresh not held'
        delivered = [e['data'] for e in selected(held, 'message-delivered') if e['seq'] > len(before_hints['events'])]
        assert delivered == [hint] * 16, 'native valid hint deliveries'
        refreshed = [e for e in selected(finished, 'transaction-created') if e['seq'] > len(before_hints['events'])]
        assert len(refreshed) == 2 and all(e['mode'] == 'readonly' for e in refreshed), 'native bounded trailing refresh'
        for tx in refreshed:
            chain = ordered(finished, 'transaction-created', 'get-success', 'transaction-complete', tx=tx['tx'])
            assert tx['role'] == 'production' and chain[1]['raw'] == before[0]['raw'], 'native production refresh exact raw'
        hints = selected(a, 'production-message', data=hint)
        assert hints and len(before_hints['events']) < hints[0]['seq'] < refreshed[0]['seq'], 'native production coalesced hint chain'
        assert not selected(a, 'notification-post', source='production') and not selected(a, 'command-start'), 'native notification source authority/rebroadcast'
        record(after[0], [], 0); record(row['uiRecord'], [], 0)
        assert before[0]['raw'] == after[0]['raw'] == row['uiRecord']['raw'], 'native notification changed durable bytes'
        assert same(before_messages['snapshot'], finished['snapshot']), 'native notification changed snapshot'
        ui = row['audits'][1]
        prefix(row['uiReady'], ui)
        initialized = one(row['uiReady'], 'transaction-created', mode='readwrite')
        ordered(row['uiReady'], 'transaction-created', 'get-success', 'transaction-complete', tx=initialized['tx'])
        assert not selected(row['uiReady'], 'message-delivered') and not selected(row['uiReady'], 'put-success'), 'native UI ready before messages'
        assert same([e['data'] for e in selected(ui, 'message-delivered')], expected_payloads + [hint]), 'native UI message delivery'
        assert not selected(ui, 'notification-post', source='production') and not selected(ui, 'command-start'), 'native UI no notification mutation'
        assert same(row['uiBefore'], row['uiAfter']) and row['uiAfter']['openRequests'] == '0' and row['uiAfter']['pinDisabled'] is True, 'native UI notification authority'
        assert row['uiAfter']['pins'] == 'Pinned revisions\n\nNo pinned revisions.', 'native expected empty UI shelf'
        refreshes = [e for e in selected(ui, 'transaction-created', mode='readonly', role='production') if e['seq'] > len(row['uiReady']['events'])]
        assert len(refreshes) == 1, 'native completed production UI refresh missing'
        refreshed = ordered(ui, 'transaction-created', 'get-success', 'transaction-complete', tx=refreshes[0]['tx'])
        hints = selected(ui, 'production-message', data=hint)
        assert hints and len(row['uiReady']['events']) < hints[0]['seq'] < refreshed[0]['seq'] < refreshed[-1]['seq'] < row['uiRecord']['binding']['created'], 'native production hint refresh chain'
        assert refreshed[0]['connection'] == initialized['connection'], 'native UI refresh production connection'
        assert refreshed[1]['raw'] == row['uiRecord']['raw'], 'native production UI refresh exact raw'
    return {'case_schema': 'native-storage-candidate/v2', 'observed': len(cases), 'acceptance': False}


def check_storage_proof(directory, require_complete=True):
    """Strict offline consistency checker; hashes never establish authenticity."""
    import re
    from check_proof import parse
    from confined_io import ConfinedRoot
    from frontend_checks import PROBE
    from run import LABEL
    root = Path(directory)
    encode = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    sha = lambda value: hashlib.sha256(value).hexdigest()
    class EverySuffix:
        def __contains__(self, unused):
            return True
    with ConfinedRoot(root) as files:
        load = lambda name: parse(files.read(name))
        proof, ownership = load('run-proof.json'), load('ownership.json')
        assert type(proof['schema_version']) is int and proof['schema_version'] == 3, 'host schema'
        assert proof['profile'] == 'native-ui-storage-host-v1' and proof['real_api_evidence'] is False, 'host scope'
        assert proof['status'] in ('PARTIAL', 'passed'), 'failed host proof'
        assert not proof.get('failure') and proof['evidence_errors'] == [] and proof.get('cleanup_errors') == [], 'host errors'
        artifacts = proof['artifacts']
        assert type(artifacts) is dict and artifacts, 'artifact manifest'
        mirror = parse(encode(proof)); mirror['artifacts'].pop('ownership.json')
        assert encode(mirror) == encode(ownership), 'ownership mirror'
        for name, digest in artifacts.items():
            assert re.fullmatch(r'[0-9a-f]{64}', digest), 'artifact digest'
            assert sha(files.read(name)) == digest, 'artifact hash: ' + name
        leaves = {name.as_posix() for name in files.files(Path('evidence'), EverySuffix(), recursive=True)}
        assert leaves <= set(artifacts), 'unmanifested evidence'
        mandatory = {'ownership.json', 'source-manifest.json', 'evidence/storage-browser.json',
                     'evidence/preimport-frontend.json', 'evidence/preimport-storage-browser.json',
                     'host-capture/dependency-preflight.stdout', 'host-capture/dependency-preflight.stderr',
                     'host-capture/storage-driver.stdout', 'host-capture/storage-driver.stderr',
                     *('evidence/dist/fixture.' + suffix for suffix in ('html', 'js', 'css'))}
        assert mandatory <= set(artifacts), 'missing required artifact'
        assert {name.as_posix() for name in files.files(Path('host-capture'), EverySuffix(), recursive=True)} == {name for name in mandatory if name.startswith('host-capture/')}, 'host capture file set'
        assert all(name in ('ownership.json', 'source-manifest.json') or name.startswith('evidence/')
                   or name in mandatory or name == proof['run'] + '-storage.log' for name in artifacts), 'unexpected artifact'
        manifest = load('source-manifest.json')
        assert manifest and encode(manifest) == encode(proof['source_sha256']), 'source manifest mirror'
        required = {'src/environment-library.tsx', 'src/environment-library.css', 'src/environment-library-contract.ts',
                    'src/library-preferences.ts', 'src/library-preferences-native.ts', 'package.json', 'package-lock.json',
                    *('tests/e2e/functional-v7/' + name for name in FIXTURE_FILES)}
        assert required <= set(manifest), 'missing frozen source'
        with ConfinedRoot(root / 'source') as source:
            assert {name.as_posix() for name in source.files(Path(), EverySuffix(), recursive=True)} == set(manifest), 'source file set'
            for name, digest in manifest.items():
                assert re.fullmatch(r'[0-9a-f]{64}', digest) and sha(source.read(name)) == digest, 'source hash: ' + name
        assert proof['staged_source_unchanged'] is True, 'changed staged source'
        assert proof['cleanup_verified'] is True and proof['remaining_owned'] == [], 'cleanup unknown/nonempty'
        verification = proof['cleanup_verification']
        assert verification['authoritative'] is True and verification['status'] == 'passed', 'cleanup authority'
        assert verification['label_ids'] == [] and verification['candidate_ids'] == {proof['run'] + '-storage': []}, 'cleanup listings'
        assert proof['stopped_frontend_unchanged'] is True, 'stopped dependency readback'
        discovery = proof['discovery']
        assert encode(discovery) == encode(proof['frontend_dependency_after']), 'dependency metadata changed'
        origin = discovery['frontend_dependency_origin']
        assert proof['dependency_selector'] == origin['Id'] == STOPPED_FRONTEND, 'dependency selector'
        assert origin['Status'] == 'exited' and origin['Running'] is False, 'dependency stopped'
        assert re.fullmatch(r'sha256:[0-9a-f]{64}', origin['Image']), 'dependency image'
        assert len(origin['Mounts']) == 2, 'origin mount binding'
        origin_mounts = {row['Destination']: row for row in origin['Mounts']}
        assert set(origin_mounts) == {'/app', '/app/node_modules'}, 'origin mount binding'
        assert origin_mounts['/app']['Type'] == 'bind' and origin_mounts['/app']['Source'] == discovery['host_root'] + '/web/arena-workbench', 'origin mount binding'
        assert origin_mounts['/app/node_modules']['Type'] == 'volume' and origin_mounts['/app/node_modules']['Name'] == discovery['deps'], 'origin mount binding'
        assert proof['image_projection'] == {'Id': PLAYWRIGHT_ID, 'Volumes': None} or proof['image_projection'] == {'Id': PLAYWRIGHT_ID, 'Volumes': {}}, 'image projection'
        name = proof['run'] + '-storage'
        assert re.fullmatch(r'arena-storage-[0-9a-f]{12}', proof['run']), 'run identity'
        assert proof['candidates'] == [name] and set(proof['created_ids']) == {name}, 'exact owned roles'
        cid = proof['created_ids'][name]
        assert re.fullmatch(r'[0-9a-f]{64}', cid), 'create ACK'
        assert encode(proof['verified_isolation']) == encode({name: True}), 'isolation verification'
        assert len(proof['containers']) == 1, 'exact container roles'
        container = proof['containers'][0]
        assert container['id'] == cid and container['name'] == '/' + name and container['image'] == PLAYWRIGHT_ID, 'inspected identity/image'
        assert container['labels'] == {LABEL: proof['run']} and container['user'] == '1000:1000', 'owned nonroot'
        host = container['host_config']
        assert host['NetworkMode'] == 'none' and host['ReadonlyRootfs'] is True, 'network/root isolation'
        assert host['CapDrop'] == ['ALL'] and not host['CapAdd'] and 'no-new-privileges' in host['SecurityOpt'], 'capability isolation'
        assert host['Privileged'] is False and not any(host.get(key) for key in ('DeviceRequests', 'Devices', 'Binds', 'VolumesFrom', 'PortBindings')), 'devices/mount authority'
        assert host['PidMode'] in ('', None) and host['IpcMode'] == 'private' and host['UsernsMode'] in ('', None), 'namespaces'
        assert type(host['PidsLimit']) is int and 0 < host['PidsLimit'] <= 256, 'PID limit'
        assert type(host['Memory']) is int and 0 < host['Memory'] <= 4294967296, 'memory limit'
        assert set(host['Tmpfs']) == {'/tmp', '/private'} and all({'rw', 'nosuid', 'nodev'} <= set(value.split(',')) for value in host['Tmpfs'].values()), 'tmpfs'
        mounts = container['mounts']
        assert len(mounts) == 3 and {row['Destination'] for row in mounts} == {'/app', '/app/node_modules', '/evidence'}, 'exact mounts'
        for row in mounts:
            destination = row['Destination']
            expected_type = 'volume' if destination == '/app/node_modules' else 'bind'
            expected_source = discovery['deps'] if expected_type == 'volume' else proof['host_output'] + ('/source' if destination == '/app' else '/evidence')
            assert row['Type'] == expected_type and row.get('Name' if expected_type == 'volume' else 'Source') == expected_source, 'mount source'
            assert row['RW'] is (destination == '/evidence'), 'mount readonly'
        assert len(proof['cleanup']) == 1, 'cleanup identity receipt'
        assert encode(proof['cleanup'][0]) == encode({'name': name, 'id': cid, 'removed': True, 'ownership_verified': True}), 'cleanup identity receipt'
        executions = proof['executions']
        assert len(executions) == 2, 'exact exec phases'
        for index, (role, args) in enumerate((('dependency-preflight', ['node', '-e', PROBE]),
                                             ('storage-driver', ['node', '--input-type=module', '-e', BROWSER_ENTRY]))):
            row = executions[index]
            assert row['role'] == role and type(row['sequence']) is int and row['sequence'] == index, 'exec ordering'
            assert row['container_id'] == cid and row['image_id'] == PLAYWRIGHT_ID, 'exec inspected binding'
            assert row['dependency_selector'] == STOPPED_FRONTEND and row['source_manifest_sha256'] == artifacts['source-manifest.json'], 'exec source/dependency binding'
            assert row['argv'] == ['docker', 'exec', '--user', '1000:1000', '-w', '/app', cid, *EXEC_ENV, *args], 'exact sanitized exec argv'
            assert not row.get('error') and type(row['exit_code']) is int, 'exec result'
            assert row['stdout'] == 'host-capture/' + role + '.stdout' and row['stderr'] == 'host-capture/' + role + '.stderr', 'exec output binding'
            assert row['capture_status'] == 'complete' and row['client_cleanup_verified'] is True, 'exec capture completion'
            assert type(row['capture_limit_bytes']) is int and row['capture_limit_bytes'] == MAX_EXEC_CAPTURE_BYTES, 'exec capture budget'
            assert sum(len(files.read(row[key])) for key in ('stdout', 'stderr')) <= MAX_EXEC_CAPTURE_BYTES, 'exec capture budget'
        assert executions[0]['exit_code'] == 0, 'real dependency preflight failed'
        receipt = load('evidence/preimport-frontend.json')
        assert encode(receipt) == encode(proof['preimport']) == encode(load('host-capture/dependency-preflight.stdout')), 'preflight stdout/receipt'
        assert type(receipt['dependency_entries']) is int and 0 < receipt['dependency_entries'] <= 250000, 'dependency scan'
        assert receipt['readonly_source_root_deps'] is True and receipt['no_new_privileges'] is True and receipt['gpu_devices'] == [], 'preimport isolation'
        for pre in (receipt, load('evidence/preimport-storage-browser.json')):
            assert pre['status'] == 'passed' and pre['before_repository_imports'] is True and pre['egress_denied'] is True, 'preimport denial'
            assert type(pre['uid']) is int and pre['uid'] == 1000 and pre['code'] in ('ENETUNREACH', 'EHOSTUNREACH', 'EPERM', 'EACCES'), 'preimport identity/denial'
        driver = load('evidence/storage-browser.json')
        assert type(driver['schema_version']) is int and driver['schema_version'] == 1 and driver['profile'] == 'native-ui-storage-probe-v1', 'driver schema'
        assert driver['real_api_evidence'] is False and driver['cleanup_verified'] is True, 'driver scope/cleanup'
        assert driver['errors'] == [] and driver['rejected'] == [] and encode(driver['network']) == encode({'overflow': False}), 'driver errors/network'
        assert driver['status'] == proof['status'] == proof['browser_status'], 'status mirror'
        assert driver['phases'] == [{'name': phase, 'status': 'completed'} for phase in
                                    ('preflight', 'imports', 'build', 'load', 'launch', 'context', 'routes', 'observe')], 'driver phases'
        assert type(driver['browser_version']) is str and driver['browser_version'], 'browser version'
        assert set(driver['fixture_sha256']) == {'fixture.html', 'fixture.js', 'fixture.css'}, 'exact dist assets'
        assert {name.as_posix() for name in files.files(Path('evidence/dist'), EverySuffix(), recursive=True)} == {'evidence/dist/' + name for name in driver['fixture_sha256']}, 'dist file set'
        fixture_total = 0
        for name, digest in driver['fixture_sha256'].items():
            raw = files.read('evidence/dist/' + name)
            assert raw and len(raw) <= 4 * 1024 * 1024 and sha(raw) == digest == artifacts['evidence/dist/' + name], 'fixture byte binding'
            fixture_total += len(raw)
            assert fixture_total <= 8 * 1024 * 1024, 'aggregate fixture budget'
        result = driver['result']; observations = result['observations']
        assert len(observations) == 2 and observations[0]['raw'] == observations[1]['raw'], 'independent durable readbacks'
        expected = [{'id': 'editor-revision:' + digit * 32, 'kind': 'editor_revision', 'revision_id': digit * 32,
                     'source_hash': digit * 64, 'canonical_hash': 'a' * 64} for digit in ('1', '2')]
        for observation in observations:
            assert observation['state'] == 'record' and observation['settledBy'] == 'transaction.oncomplete', 'durable completion'
            assert type(observation['raw']) is str and len(observation['raw']) <= 32768, 'durable record budget'
            value = parse(observation['raw'])
            assert set(value) == {'schemaVersion', 'revision', 'preferences'} and type(value['schemaVersion']) is int and value['schemaVersion'] == 1, 'durable schema'
            assert type(value['revision']) is int and 0 <= value['revision'] <= 9007199254740991, 'durable revision'
            prefs = value['preferences']
            assert set(prefs) == {'version', 'pins', 'recents'} and type(prefs['version']) is int and prefs['version'] == 1, 'preference schema'
            assert len(encode(prefs)) <= 16384 and type(prefs['pins']) is list and sorted(map(encode, prefs['pins'])) == sorted(map(encode, expected)), 'exact expected durable pins'
            assert type(prefs['recents']) is list and len(prefs['recents']) <= 12 and len(set(map(encode, prefs['recents']))) == len(prefs['recents']), 'bounded recents'
            assert all(item in expected for item in prefs['recents']), 'exact recent reference'
        assert result['legacyBefore'] == result['legacyAfter'] and result['legacyBefore'] is None, 'unseeded legacy sample'
        assert result['schedule'] == 'concurrent clicks; transaction overlap NOT witnessed', 'schedule disclosure'
        assert encode(driver['required_cases']) == encode(proof['required_cases']), 'required cases mirror'
        candidate = None
        if 'case_schema' in result or 'cases' in result:
            assert result.get('case_schema') == 'native-storage-candidate/v2', 'native case schema'
            assert driver['required_cases'] == {name: 'observed' for name in REQUIRED_CASES}, 'native case flags'
            candidate = validate_native_cases(result['cases'])
            case_paths = {'evidence/native-case-' + name + '.json' for name in REQUIRED_CASES}
            assert case_paths <= set(artifacts), 'missing native case artifact'
            assert {name for name in leaves if name.startswith('evidence/native-case-')} == case_paths, 'native case artifact set'
            for name, row in result['cases'].items():
                assert encode(load('evidence/native-case-' + name + '.json')) == encode(row), 'native case artifact mirror'
                assert row['browser_version'] == driver['browser_version'], 'native case browser binding'
        else:
            assert driver['required_cases'] == {name: 'NOT-RUN' for name in REQUIRED_CASES}, 'unsupported native case claim'
            assert not any(name.startswith('evidence/native-case-') for name in leaves), 'unclaimed native case artifact'
        assert proof['status'] == 'PARTIAL' and executions[1]['exit_code'] == 2, 'partial exit/status'
        assert not require_complete, 'native cases incomplete or awaiting parent review: PARTIAL is not acceptance'
        return {'status': 'PARTIAL', 'acceptance': False, 'scope': 'artifact consistency only; not execution authenticity',
                **({'candidate': candidate} if candidate else {})}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--safeunits', action='store_true')
    modes.add_argument('--browser', action='store_true')
    modes.add_argument('--check', type=Path, help='Strict acceptance checker; incomplete native cases fail')
    modes.add_argument('--check-partial', type=Path, help='Inspect partial consistency only; always nonzero')
    parser.add_argument('--allow-storage-browser', action='store_true', help='Explicitly run the reviewed bounded fixture; not full storage/API acceptance')
    parser.add_argument('--frontend-dependency-container', default=STOPPED_FRONTEND)
    options = parser.parse_args(argv)
    if options.check or options.check_partial:
        assert not options.allow_storage_browser, 'checker cannot carry browser approval'
        try:
            result = check_storage_proof(options.check or options.check_partial, require_complete=options.check is not None)
            print(json.dumps(result, sort_keys=True))
            return 2 if result['status'] == 'PARTIAL' else 0
        except (AssertionError, OSError, ValueError, KeyError, TypeError) as error:
            print(json.dumps({'status': 'failed', 'acceptance': False, 'error': str(error)}))
            return 1
    if not options.safeunits:
        if options.browser and options.allow_storage_browser and REVIEWED_BROWSER is True:
            import uuid
            here = Path(__file__).absolute().parent
            root = here.parents[4]
            output = here / '.runs' / ('arena-storage-' + uuid.uuid4().hex[:12])
            return browser_lifecycle(root, output, options.frontend_dependency_container)
        print(json.dumps(gate_record(), sort_keys=True))
        return 2  # Before discovery/staging/image/import activity. No env/flag bypass.
    assert not options.allow_storage_browser, 'safeunits cannot carry browser approval'
    return safeunits(options.frontend_dependency_container)


def inside_units():
    """Use F0's actual kernel preflight before the explicit additive test cohort."""
    import unittest
    from api import preflight, write
    preflight()
    import self_test
    selected = (*self_test.UNIT_SUITES[:-1], 'test_ui_storage_probe.py', self_test.UNIT_SUITES[-1])
    suites = []
    for name in selected:  # Permanent GitPython process-denial audit remains last.
        with (Path('/evidence') / (name + '.log')).open('w') as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(
                unittest.defaultTestLoader.discover(str(Path(__file__).parent), pattern=name))
        suites.append({'suite': name, 'passed': result.wasSuccessful(), 'tests': result.testsRun,
                       'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped)})
    passed = all(row['passed'] and row['tests'] and not row['skipped'] for row in suites)
    write('self-test.json', {'schema_version': 2, 'scope': 'F0 and native-storage harness units only; no browser/build/API acceptance',
                            'passed': passed, 'tests': sum(row['tests'] for row in suites), 'suites': suites})
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(inside_units() if sys.argv[1:] == ['--inside'] else main())
