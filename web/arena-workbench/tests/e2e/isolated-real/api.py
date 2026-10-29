# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Harness-only injection; production CLI, sessions, CSRF, workers, journal and store."""
import asyncio
import json
import os
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path('/workspaces/isaaclab_arena')
BASE = Path('/acceptance')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, '/acceptance/pydeps')
assert os.getuid() != 0
os.umask(0o077)
(BASE / 'api-identity.json').write_text(json.dumps({'pid': os.getpid(), 'stat': Path(f'/proc/{os.getpid()}/stat').read_text(),
                                                  'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text()}))


def audit(event, args):
    if event == 'socket.connect' and args[0].family != socket.AF_UNIX:
        with (BASE / 'forbidden-network.jsonl').open('a') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'event': event, 'address': str(args[1])}) + '\n')
        raise RuntimeError('Harness denies all IP socket connections')


sys.addaudithook(audit)
from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore
from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena.agentic_environment_generation.workbench.research_publication import PublicationAttempts
from isaaclab_arena_examples.agentic_environment_generation.web_api import __main__ as launcher
from isaaclab_arena_examples.agentic_environment_generation.web_api import editor_execution, generation, graph_access
from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_authorization import PublicationAuthorization
from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_scheduler import PublicationScheduler

# Observation only: retain production implementations, including scheduler recovery.
publication_calls = {'accept': 0, 'enqueue': 0, 'issue_grant': 0}
original_accept = PublicationScheduler.accept
original_enqueue = PublicationScheduler.enqueue
original_issue = PublicationAuthorization.issue


def observed_accept(self, *args, **kwargs):
    publication_calls['accept'] += 1
    return original_accept(self, *args, **kwargs)


async def observed_enqueue(self, *args, **kwargs):
    publication_calls['enqueue'] += 1
    return await original_enqueue(self, *args, **kwargs)


def observed_issue(self, *args, **kwargs):
    publication_calls['issue_grant'] += 1
    return original_issue(self, *args, **kwargs)


PublicationScheduler.accept = observed_accept
PublicationScheduler.enqueue = observed_enqueue
PublicationAuthorization.issue = observed_issue


def no_snapshots(*args):
    raise ImportError('No GPU adapter in isolated acceptance')


def configuration():
    return {'provider': 'openai', 'model': 'harness-deterministic-no-provider',
            'api_key': 'isolated-inert-key-not-a-provider-credential', 'base_url': 'http://127.0.0.1:1/v1',
            'trusted_server': True}


generation.configuration = configuration
graph_access.configuration = lambda: None
editor_execution.make_snapshot_service = no_snapshots
original_spawn = asyncio.create_subprocess_exec


async def spawn(*args, **kwargs):
    assert args[1:4] == ('-u', '-m', 'isaaclab_arena_examples.agentic_environment_generation.web_api.generation_worker'), args
    script = ROOT / 'web/arena-workbench/tests/e2e/isolated-real/worker.py'
    with (BASE / 'worker-stderr.log').open('ab') as errors:
        kwargs['stderr'] = errors
        child = await original_spawn(args[0], '-u', str(script), *args[4:], **kwargs)
    read = child.stdout.readline

    async def observed_read():
        line = await read()
        if line:
            with (BASE / 'worker-frames.jsonl').open('ab') as stream:
                stream.write(line)
        return line

    child.stdout.readline = observed_read
    with (BASE / 'spawn-proof.jsonl').open('a') as stream:
        stream.write(json.dumps({'pid': child.pid, 'original_command': list(args), 'injected_script': str(script),
                                 'start_new_session': kwargs.get('start_new_session'),
                                 'start_identity': Path(f'/proc/{child.pid}/stat').read_text()}) + '\n')
    return child


asyncio.create_subprocess_exec = spawn
original_create = launcher.create_app


def create(*args, **kwargs):
    kwargs['publication_profiles'] = {'isolated-unreachable': {
        'connection': {'uri': 'bolt://127.0.0.1:1', 'user': 'harness',
                       'password': 'isolated-inert-graph-marker', 'database': 'neo4j'},
        'immutable_scope': True}}
    # Explicit test setup under the launcher's lease, before enabled API lifespan.
    # Refuse reuse: only this run's empty private volume may be initialized.
    state = Path(args[0])
    root = Path('/private/managed')
    assert state == Path('/private/state') and not root.exists()
    assert not (state / 'journal.sqlite3').exists()
    journal = Journal(state / 'journal.sqlite3')
    try:
        with ResearchStore.create(journal, root, 'isolated', protect_public=lambda value: None) as store:
            ledger = PublicationAttempts(journal, store.registry, initialize=True)
            ledger.initialize_worker_support()
            assert ledger.worker_support_ready()
            (BASE / 'bootstrap.json').write_text(json.dumps({'fresh_private_only': True,
                'before_enabled_lifespan': True, 'worker_support_ready': True,
                'registry_id': store.registry.registry_id}))
    finally:
        journal.close()
    kwargs['publication_enabled'] = True
    app = original_create(*args, **kwargs)
    app.state.neo4j_available = False
    lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def prepared(application):
        async with lifespan(application):
            assert app.state.publication_admitting is True
            assert type(app.state.publication_scheduler).__name__ == 'PublicationScheduler'
            try:
                yield
            finally:
                (BASE / 'api-before-cleanup.json').write_text(json.dumps({
                    'pid': os.getpid(), 'uid': os.getuid(), 'pending_workers': app.state.journal.pending_workers(),
                    'publication_enabled': app.state.publication_enabled,
                    'publication_admitting': app.state.publication_admitting,
                    'publication_scheduler': app.state.publication_scheduler is not None,
                    'publication_workers': app.state.publication_scheduler.worker_count,
                    'publication_slots': len(app.state.publication_scheduler._slots),
                    'publication_tasks': len(app.state.publication_scheduler._tasks),
                    'publication_grants': len(app.state.publication_authorization._records),
                    'publication_calls': publication_calls,
                }, indent=2))
        (BASE / 'api-cleanup.json').write_text(json.dumps({'lifespan_closed': app.state._cleanup.closed}))

    app.router.lifespan_context = prepared
    return app


launcher.create_app = create
sys.argv = ['isolated-api', '--state-dir', '/private/state', '--socket', str(BASE / 'ipc/api.sock'),
            '--origin', 'http://127.0.0.1:31847', '--research-store', 'isolated=/private/managed']
launcher.main()
(BASE / 'socket-cleanup.json').write_text(json.dumps({'socket_absent': not (BASE / 'ipc/api.sock').exists()}))
