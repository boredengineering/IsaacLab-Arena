#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Run bounded offline acceptance in owned containers, never the live API namespace."""
import hashlib
import json
import os
import subprocess
import tempfile
import time
import traceback
import uuid
from pathlib import Path

ROOT = Path('/workspaces/IsaacLab-Arena')
HERE = ROOT / 'web/arena-workbench/tests/e2e/isolated-real'
OUT = Path(tempfile.mkdtemp(prefix='arena-real-acceptance-', dir='/tmp'))
RUN = 'arena-real-' + uuid.uuid4().hex[:12]
owned = []
volumes = []
proof = {'run': RUN, 'output': str(OUT), 'containers': [], 'cleanup': [], 'status': 'starting'}
(OUT / 'test-scripts').mkdir()
for source in HERE.iterdir():
    if source.is_file():
        (OUT / 'test-scripts' / source.name).write_bytes(source.read_bytes())
source_paths = [*ROOT.glob('isaaclab_arena_examples/agentic_environment_generation/web_api/*.py'),
                *ROOT.glob('isaaclab_arena/agentic_environment_generation/workbench/*.py'),
                *ROOT.glob('web/arena-workbench/src/*')]
proof['source_sha256_at_start'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in source_paths if p.is_file()}


def cmd(*args, timeout=180, check=True):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'{args!r}: {result.stdout}\n{result.stderr}')
    return result


def docker(*args, **kwargs):
    return cmd('docker', *args, **kwargs).stdout.strip()


def inspect(cid):
    return json.loads(docker('inspect', cid))[0]


def create(label, image, *args, entrypoint='sh', mounts=(), user='1000:1234', workdir='/tmp'):
    argv = ['create', '--name', f'{RUN}-{label}', '--label', f'arena.acceptance={RUN}',
            '--network', 'none', '--init', '--user', user, '--workdir', workdir,
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--env', 'NVIDIA_VISIBLE_DEVICES=void', '--env', 'CUDA_VISIBLE_DEVICES=',
            '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', 'HOME=/tmp', '--entrypoint', entrypoint]
    for mount in mounts:
        argv += ['--mount', mount]
    cid = docker(*argv, image, *args)
    owned.append(cid)
    info = inspect(cid)
    proof['containers'].append({'id': cid, 'label': label, 'image': info['Image'],
                                'network': info['HostConfig']['NetworkMode'], 'mounts': info['Mounts'],
                                'devices': info['HostConfig'].get('DeviceRequests'), 'user': info['Config']['User']})
    (OUT / 'ownership.json').write_text(json.dumps(proof, indent=2))
    return cid


def finite(cid, name, timeout=150):
    try:
        result = cmd('docker', 'start', '-a', cid, timeout=timeout, check=False)
        (OUT / f'{name}.log').write_text(result.stdout + result.stderr)
        state = inspect(cid)['State']
        assert not state['Running'], state
        assert state['ExitCode'] == 0, (OUT / f'{name}.log').read_text()
    finally:
        (OUT / f'{name}-inspect.json').write_text(json.dumps(inspect(cid), indent=2))


def stop_owned(cid):
    info = inspect(cid)
    if info['State']['Running'] and info['Name'].endswith('-api'):
        signal_code = "import json,os,signal; from pathlib import Path; r=json.loads(Path('/acceptance/api-identity.json').read_text()); p=r['pid']; f=os.pidfd_open(p); assert Path('/proc/sys/kernel/random/boot_id').read_text()==r['boot_id']; assert Path(f'/proc/{p}/stat').read_text().rsplit(')',1)[1].split()[19]==r['stat'].rsplit(')',1)[1].split()[19]; signal.pidfd_send_signal(f,signal.SIGTERM); os.close(f)"
        signalled = cmd('docker', 'exec', '--user', '1000:1234', cid, '/isaac-sim/python.sh', '-c', signal_code, check=False)
        (OUT / 'api-signal.log').write_text(signalled.stdout + signalled.stderr)
        if signalled.returncode == 0:
            try:
                cmd('docker', 'wait', cid, timeout=18)
            except subprocess.TimeoutExpired:
                pass
    if inspect(cid)['State']['Running']:
        docker('stop', '--time', '12', cid, timeout=25)


def live_snapshot(runtime):
    # File bytes only: do not connect to live sessions, acquire leases, or open SQLite RW.
    code = '''import hashlib,json,stat
from pathlib import Path
root=Path('/eval/.wb/6e74675cd31c/state')
items={}
for p in sorted(root.rglob('*')):
 if p.is_symlink() or not p.is_file(): continue
 s=p.stat()
 h=hashlib.sha256()
 with p.open('rb') as f:
  while b:=f.read(1048576): h.update(b)
 items[str(p.relative_to(root))]={'sha256':h.hexdigest(),'size':s.st_size,'mtime_ns':s.st_mtime_ns,'inode':s.st_ino}
print(json.dumps(items,sort_keys=True))'''
    return json.loads(docker('exec', '--user', '1000:1234', runtime, '/isaac-sim/python.sh', '-c', code, timeout=180))


def alive_identity(cid):
    state = inspect(cid)['State']
    return {key: state[key] for key in ('Running', 'Pid', 'StartedAt', 'Restarting')}


try:
    running = [inspect(cid) for cid in docker('ps', '-q').splitlines()]
    editor = next(c for c in running if any(m['Destination'] == str(ROOT) for m in c['Mounts']))
    host_root = next(m['Source'] for m in editor['Mounts'] if m['Destination'] == str(ROOT))
    runtime = next(c for c in running if any(m['Source'] == host_root and m['Destination'] == '/workspaces/isaaclab_arena' for m in c['Mounts']))
    frontend = next(c for c in running if any(m['Source'] == host_root + '/web/arena-workbench' and m['Destination'] == '/app' for m in c['Mounts']))
    deps = next(m['Name'] for m in frontend['Mounts'] if m['Destination'] == '/app/node_modules')
    frontend_image = frontend['Image']
    if cmd('docker', 'image', 'inspect', frontend_image, check=False).returncode:
        # An old live container may reference a pruned image; use its locally installed service tag.
        frontend_image = frontend['Name'].lstrip('/').rsplit('-', 1)[0] + ':latest'
        docker('image', 'inspect', frontend_image)
    observed = [runtime['Id'], frontend['Id']] + [c['Id'] for c in running if c['Name'] == '/neo4j-arena']
    before_identities = {c: alive_identity(c) for c in observed}
    before = live_snapshot(runtime['Id'])
    (OUT / 'live-before.json').write_text(json.dumps(before, indent=2))
    (OUT / 'live-container-before.json').write_text(json.dumps(before_identities, indent=2))
    proof['live_state_root'] = '/eval/.wb/6e74675cd31c/state'
    proof['live_files_count'] = len(before)
    shared, private = RUN + '-evidence', RUN + '-private'
    for volume in (shared, private):
        docker('volume', 'create', '--label', f'arena.acceptance={RUN}', volume)
        volumes.append(volume)
    public_mount = f'type=volume,src={shared},dst=/acceptance'
    private_mount = f'type=volume,src={private},dst=/private'
    source_mount = f'type=bind,src={host_root},dst=/workspaces/isaaclab_arena,readonly'
    front_mount = f'type=bind,src={host_root}/web/arena-workbench,dst=/app,readonly'
    deps_mount = f'type=volume,src={deps},dst=/app/node_modules,readonly'
    # Only new-volume ownership initialization runs as root; no host paths are mounted.
    init_args = ['create', '--name', RUN + '-volume-init', '--label', f'arena.acceptance={RUN}', '--network', 'none',
                 '--user', '0:0', '--entrypoint', 'sh', '--mount', public_mount, '--mount', private_mount,
                 frontend_image, '-c', 'chown 1000:1234 /acceptance /private && chmod 700 /acceptance /private']
    init = docker(*init_args); owned.append(init)
    finite(init, 'volume-init')
    build = create('build', frontend_image, '-c',
                   'node node_modules/vite/bin/vite.js build --configLoader runner --outDir /acceptance/dist',
                   mounts=(public_mount, front_mount, deps_mount), workdir='/app')
    finite(build, 'build', 180)
    api = create('api', runtime['Image'],
                 '/workspaces/isaaclab_arena/web/arena-workbench/tests/e2e/isolated-real/api.py',
                 entrypoint='/isaac-sim/python.sh', mounts=(public_mount, private_mount, source_mount),
                 workdir='/workspaces/isaaclab_arena')
    # Reuse the actual locally installed driver package; no package download or graph connection.
    dependency_path = docker('exec', '--user', '1000:1234', runtime['Id'], '/isaac-sim/python.sh', '-c',
                             'import neo4j; from pathlib import Path; print(Path(neo4j.__file__).parent)')
    dependency_dir = OUT / 'runtime-deps'
    dependency_dir.mkdir()
    docker('cp', f"{runtime['Id']}:{dependency_path}", str(dependency_dir / 'neo4j'))
    docker('cp', str(dependency_dir), f'{api}:/acceptance/pydeps')
    docker('start', api)
    probe = "import http.client,socket,json; c=http.client.HTTPConnection('127.0.0.1:31847',timeout=1); c.sock=socket.socket(socket.AF_UNIX); c.sock.connect('/acceptance/ipc/api.sock'); c.request('GET','/api/health'); r=c.getresponse(); assert r.status==200; assert json.loads(r.read())['status']=='ok'; print('real UDS health ready')"
    deadline = time.monotonic() + 45
    while True:
        assert inspect(api)['State']['Running'], 'Isolated API exited; see preserved API log'
        check = cmd('docker', 'exec', '--user', '1000:1234', api, '/isaac-sim/python.sh', '-c', probe, check=False)
        if check.returncode == 0:
            (OUT / 'uds-health.txt').write_text(check.stdout)
            break
        assert time.monotonic() < deadline, check.stderr
        time.sleep(0.1)  # Backoff only after a failed real health probe.
    browser = create('browser', 'mcr.microsoft.com/playwright:v1.58.2-noble',
                     '/app/tests/e2e/isolated-real/browser.mjs', entrypoint='node',
                     mounts=(public_mount, front_mount, deps_mount), workdir='/app')
    finite(browser, 'browser', 240)
    stop_owned(api)
    verifier = create('disk-verifier', runtime['Image'],
                      '/workspaces/isaaclab_arena/web/arena-workbench/tests/e2e/isolated-real/verify_disk.py',
                      entrypoint='/isaac-sim/python.sh', mounts=(public_mount, private_mount + ',readonly', source_mount),
                      workdir='/workspaces/isaaclab_arena')
    finite(verifier, 'disk-verifier', 45)
    proof['status'] = 'passed'
except BaseException:
    proof['status'] = 'failed'
    proof['failure'] = traceback.format_exc()
    print(proof['failure'])
finally:
    for cid in reversed(owned):
        try:
            info = inspect(cid)
            stop_owned(cid)
            state = inspect(cid)['State']
            logs = cmd('docker', 'logs', cid, check=False)
            (OUT / f"{info['Name'].lstrip('/')}-logs.txt").write_text(logs.stdout + logs.stderr)
            if info['Name'].endswith('-api'):
                docker('cp', f'{cid}:/private', str(OUT / 'private'), timeout=180)
                docker('cp', f'{cid}:/acceptance/.', str(OUT), timeout=180)
                (OUT / 'api-container-stopped.json').write_text(json.dumps(state, indent=2))
            docker('rm', cid)
            absent = cmd('docker', 'inspect', cid, check=False).returncode != 0
            assert absent
            proof['cleanup'].append({'id': cid, 'stopped': not state['Running'], 'removed': absent, 'exit_code': state['ExitCode']})
        except BaseException as exc:
            proof['cleanup'].append({'id': cid, 'error': str(exc)})
            proof['status'] = 'failed'
    for volume in reversed(volumes):
        result = cmd('docker', 'volume', 'rm', volume, check=False)
        proof['cleanup'].append({'volume': volume, 'removed': result.returncode == 0})
        if result.returncode: proof['status'] = 'failed'
    if 'before' in globals():
        try:
            after = live_snapshot(runtime['Id'])
            (OUT / 'live-after.json').write_text(json.dumps(after, indent=2))
            after_identities = {c: alive_identity(c) for c in observed}
            (OUT / 'live-container-after.json').write_text(json.dumps(after_identities, indent=2))
            proof['live_unchanged'] = before == after
            proof['live_containers_unchanged'] = before_identities == after_identities
            proof['changed_live_files'] = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
            if not proof['live_unchanged'] or not proof['live_containers_unchanged']: proof['status'] = 'failed'
        except BaseException:
            proof['verification_error'] = traceback.format_exc()
            proof['status'] = 'failed'
    forbidden = OUT / 'forbidden-network.jsonl'
    proof['api_worker_forbidden_network_attempts'] = len(forbidden.read_text().splitlines()) if forbidden.exists() else 0
    if proof['api_worker_forbidden_network_attempts']: proof['status'] = 'failed'
    proof['source_changes_during_run'] = [path for path, digest in proof['source_sha256_at_start'].items()
                                         if not (ROOT / path).is_file() or hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest]
    proof['artifacts'] = {str(p.relative_to(OUT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(OUT.rglob('*')) if p.is_file() and not p.is_symlink()}
    (OUT / 'run-proof.json').write_text(json.dumps(proof, indent=2))
    print(json.dumps({'status': proof['status'], 'output': str(OUT), 'live_unchanged': proof.get('live_unchanged'),
                      'live_containers_unchanged': proof.get('live_containers_unchanged')}))
raise SystemExit(0 if proof['status'] == 'passed' else 1)
