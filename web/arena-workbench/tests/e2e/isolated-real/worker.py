# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Trusted deterministic generator inside the unchanged production worker protocol."""
import hashlib
import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path('/workspaces/isaaclab_arena')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, '/acceptance/pydeps')


def audit(event, args):
    if event == 'socket.connect' and args[0].family != socket.AF_UNIX:
        with open('/acceptance/forbidden-network.jsonl', 'a') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'event': event, 'address': str(args[1])}) + '\n')
        raise RuntimeError('Harness denies all IP socket connections')


sys.addaudithook(audit)
from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
from isaaclab_arena_examples.agentic_environment_generation.web_api import generation, generation_worker


def deterministic(inputs, emit, *, config, graph_config=None):
    assert graph_config is None, 'Graph work is not authorized by this harness'
    assert config['model'] == 'harness-deterministic-no-provider'
    operation = inputs['operation']
    assert operation in {'new', 'refine'}
    if operation == 'new':
        assert inputs.get('base_yaml') is None and inputs.get('document_id') is None
        text = (ROOT / 'isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml').read_text()
        snapshot = empty_snapshot(inputs['prompt'])
    else:
        text = inputs['base_yaml']
        snapshot = empty_snapshot('', status='not_requested', warning='')
    text += f'\n# Trusted isolated acceptance {operation}; no provider/graph/simulator execution.\n'
    with open('/acceptance/worker-proof.jsonl', 'a') as stream:
        stream.write(json.dumps({'pid': os.getpid(), 'ppid': os.getppid(), 'operation': operation,
                                 'input_sha256': hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
                                 'yaml_sha256': hashlib.sha256(text.encode()).hexdigest(),
                                 'catalogue_sha256': inputs['execution_catalogue_sha256'],
                                 'protocol': 'production generation_worker.main; only generation.generate replaced'}) + '\n')
    return {'yaml_text': text, 'validation': {}, 'traces': [], 'publication': 'not_published',
            'warnings': ['Not published to Neo4j. No simulation or policy evaluation was run.'],
            'operation': operation, 'prior_snapshot': snapshot,
            'catalogue_sha256': inputs['execution_catalogue_sha256']}


generation.generate = deterministic
raise SystemExit(generation_worker.main())
