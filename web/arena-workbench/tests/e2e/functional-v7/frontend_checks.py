# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Explicitly gated ordinary npm typecheck/build in a nonroot offline sandbox.

Never use this entry to rephrase or retry a tool-approval denial. Dependencies are
trusted installed mutable frontend bytes, NOT immutable package provenance.
"""
import hashlib
import json
import os
import signal
import subprocess
import uuid
from pathlib import Path


def command(mode, approved):
    if approved is not True:
        raise ValueError("Frontend verification requires explicit --allow-frontend-verification")
    if mode == "typecheck":
        return ["npm", "run", "typecheck"]
    if mode == "build":
        return ["npm", "run", "build", "--", "--outDir", "/evidence/dist", "--configLoader", "runner"]
    raise ValueError("Only ordinary typecheck/build commands are approved; no arbitrary npm command")


PROBE = r'''const fs=require('node:fs'),net=require('node:net'),path=require('node:path');
if(process.getuid()!==1000)throw Error('nonroot uid required');
const status=fs.readFileSync('/proc/self/status','utf8');
if(!/^CapEff:\s*0+$/m.test(status)||!/^NoNewPrivs:\s*1$/m.test(status))throw Error('privilege boundary');
if(JSON.stringify(fs.readdirSync('/sys/class/net'))!==JSON.stringify(['lo']))throw Error('network interface');
if(fs.readdirSync('/private').length)throw Error('fresh state required');
const mounts=fs.readFileSync('/proc/self/mountinfo','utf8').split('\n').map(x=>x.split(' '));
for(const p of ['/','/app','/app/node_modules'])if(!mounts.some(x=>x[4]===p&&x[5].split(',').includes('ro')))throw Error('read-only mount missing');
if(fs.readdirSync('/dev').some(n=>n.startsWith('nvidia')||n==='dri'))throw Error('GPU device');
const root='/app/node_modules';let entries=0,bytes=0;
function walk(dir){for(const ent of fs.readdirSync(dir,{withFileTypes:true})){
 const p=path.join(dir,ent.name);if(++entries>250000)throw Error('dependency entry budget');
 if(/^(\.env(?:\..*)?|\.aws|\.ssh|\.azure|credentials(?:\..*)?|id_rsa|id_ed25519)$/i.test(ent.name))throw Error('sensitive dependency entry');
 const s=fs.lstatSync(p);
 if(s.isSymbolicLink()){if(!fs.realpathSync(p).startsWith(root+'/'))throw Error('dependency link escape');continue;}
 if(s.isDirectory())walk(p);else if(!s.isFile()||s.nlink!==1)throw Error('special/hardlink');
 else if((bytes+=s.size)>1500000000)throw Error('dependency size budget');
}}
walk(root);
const probe=net.connect({host:'198.18.0.1',port:9});probe.setTimeout(2000,()=>{probe.destroy();process.exit(2)});
probe.on('connect',()=>{probe.destroy();process.exit(3)});probe.on('error',e=>{
 if(!['ENETUNREACH','EHOSTUNREACH','EPERM','EACCES'].includes(e.code))process.exit(4);
 const proof={status:'passed',uid:process.getuid(),egress_denied:true,code:e.code,before_repository_imports:true,
 readonly_source_root_deps:true,no_new_privileges:true,gpu_devices:[],dependency_entries:entries,
 dependency_trust:'trusted mutable installed frontend volume; not immutable provenance'};
 fs.writeFileSync('/evidence/preimport-frontend.json',JSON.stringify(proof));console.log(JSON.stringify(proof));});
'''


def capture(root, destination):
    from confined_io import ConfinedRoot, new_destination
    suffixes = {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.json', '.css', '.svg', '.png', '.jpg', '.jpeg', '.woff', '.woff2', '.txt', '.md'}
    with ConfinedRoot(root) as source:
        names = {Path(name) for name in ('package.json', 'package-lock.json', 'tsconfig.json', 'index.html')}
        names.update(source.files(Path(), {'.ts'}))
        names.update(source.files(Path('src'), suffixes, recursive=True))
        # Typecheck the authored E2E sources without running their workflows.
        for folder in ('tests', 'tests/e2e'):
            names.update(source.files(Path(folder), {'.ts', '.tsx'}))
        assert len(names) <= 10000
        data = {name: source.read(name) for name in names}
        assert sum(map(len, data.values())) <= 128 * 1024 * 1024
    package = json.loads(data[Path('package.json')])
    assert package['scripts']['typecheck'] == 'tsc --noEmit'
    assert package['scripts']['build'] == 'tsc --noEmit && vite build'
    assert not any(name in package['scripts'] for name in ('pretypecheck', 'posttypecheck', 'prebuild', 'postbuild'))
    with new_destination(destination) as target:
        for name, value in sorted(data.items()):
            target.write_new(name, value)
    (destination / 'node_modules').mkdir()
    return {name.as_posix(): hashlib.sha256(value).hexdigest() for name, value in data.items()}


def main(mode, approved=False, frontend_dependency_container=None):
    npm = command(mode, approved)  # Explicit admission before any Docker operation.
    from confined_io import read_confined
    from run import OwnedRun, compare_source, discover_frontend, docker, hash_evidence, image_metadata, verify_container
    here = Path(__file__).resolve().parent
    root = here.parents[4]
    token = 'arena-f0-' + mode + '-' + uuid.uuid4().hex[:12]
    output = here / '.runs' / token
    output.mkdir(parents=True)
    run = OwnedRun(output, token)
    run.proof.update(status='failed', scope='ordinary npm ' + mode + '; no browser/API/live workflow',
                     npm_argv=npm, dependency_trust='trusted mutable installed frontend volume; not immutable provenance')
    print(json.dumps({'output': str(output), 'command': npm}), flush=True)
    previous = {}
    def interrupted(signum, frame):
        raise InterruptedError(f'signal {signum}')
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, interrupted)
    try:
        discovery = discover_frontend(root, frontend_dependency_container=frontend_dependency_container)
        run.proof['discovery'] = discovery
        manifest = capture(root / 'web/arena-workbench', output / 'source')
        run.proof['source_sha256'] = manifest
        (output / 'source-manifest.json').write_text(json.dumps(manifest, indent=2))
        (output / 'evidence').mkdir(mode=0o700)
        os.chown(output / 'evidence', 1000, 1000)
        host = discovery['host_root'] + '/' + output.relative_to(root).as_posix()
        mounts = [f'type=bind,src={host}/source,dst=/app,readonly',
                  f'type=volume,src={discovery["deps"]},dst=/app/node_modules,readonly',
                  f'type=bind,src={host}/evidence,dst=/evidence']
        image = image_metadata('node:22.22.0-bookworm-slim')['Id']
        cid = run.create('npm', image, '/usr/bin/env',
                         ['-i', 'HOME=/tmp', 'PATH=/usr/local/bin:/usr/bin:/bin', 'sleep', '360'], mounts)
        verify_container(run, cid, mounts)
        docker('start', cid)
        env = ['/usr/bin/env', '-i', 'HOME=/tmp', 'PATH=/usr/local/bin:/usr/bin:/bin',
               'NPM_CONFIG_OFFLINE=true', 'NPM_CONFIG_IGNORE_SCRIPTS=true', 'NPM_CONFIG_CACHE=/tmp/npm-cache']
        probe = docker('exec', '--user', '1000:1000', cid, *env, 'node', '-e', PROBE)
        run.proof['preimport'] = json.loads(probe)
        run.save()
        argv = ['docker', 'exec', '--user', '1000:1000', '-w', '/app', cid, *env, *npm]
        run.proof['exact_command'] = argv
        print(json.dumps({'exact_command': argv}), flush=True)
        result = subprocess.run(argv, capture_output=True, text=True, timeout=240)
        (output / 'evidence' / (mode + '.log')).write_text(result.stdout + result.stderr)
        print(result.stdout + result.stderr, flush=True)
        run.proof['exit_code'] = result.returncode
        assert result.returncode == 0, mode + ' failed; see exact log'
        if mode == 'build':
            assert read_confined(output, 'evidence/dist/index.html')
        run.proof['status'] = 'passed'
    except BaseException as error:
        run.proof['failure'] = type(error).__name__ + ': ' + str(error)
        if isinstance(error, subprocess.TimeoutExpired):
            (output / 'evidence/timeout.log').write_bytes((error.stdout or b'') + (error.stderr or b''))
    finally:
        for signum in previous:
            signal.signal(signum, signal.SIG_IGN)
        try:
            run.proof['cleanup_verified'] = run.cleanup()
            errors = []
            manifest = run.proof.get('source_sha256', {})
            changed, rejected = compare_source(output / 'source', manifest)
            run.proof['staged_source_unchanged'] = bool(manifest) and not changed
            errors.extend(changed + rejected)
            run.proof['artifacts'] = {}
            if (output / 'evidence').exists():
                hash_evidence(output, run.proof['artifacts'], errors)
            if (output / 'source-manifest.json').exists():
                run.proof['artifacts']['source-manifest.json'] = hashlib.sha256(read_confined(output, 'source-manifest.json')).hexdigest()
            run.proof['evidence_errors'] = errors
            if errors or not manifest or not run.proof['cleanup_verified']:
                run.proof['status'] = 'failed'
            run.save()
            run.proof['artifacts']['ownership.json'] = hashlib.sha256(read_confined(output, 'ownership.json')).hexdigest()
            (output / 'run-proof.json').write_text(json.dumps(run.proof, indent=2))
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        print(json.dumps({'status': run.proof['status'], 'output': str(output),
                          'remaining_owned': run.proof.get('remaining_owned'), 'failure': run.proof.get('failure')}), flush=True)
    return 0 if run.proof['status'] == 'passed' else 1
