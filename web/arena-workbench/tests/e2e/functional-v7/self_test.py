#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Run mocked lifecycle faults inside an owned nonroot network-none sandbox."""
import hashlib
import json
import os
import signal
import sys
import unittest
import uuid
from pathlib import Path


UNIT_SUITES = ("test_run.py", "test_confined_io.py", "test_api.py", "test_check_proof.py",
               "test_producers.py", "test_authoring_proof.py", "test_manual_research.py", "test_metadata_gitpython.py")
UNIT_SOURCES = ("run.py", "api.py", "self_test.py", "confined_io.py", "stage.py", "check_proof.py",
                "backend_checks.py", "frontend_checks.py", "manual_research.py", *UNIT_SUITES)

# Builtins-only preflight, then import-safe correlation units. No Vite,
# Playwright, dependency volume, browser, package execution or child process.
NODE_UNITS = r'''
import assert from 'node:assert/strict';
import {readFileSync, readdirSync, writeFileSync, renameSync} from 'node:fs';
import net from 'node:net';
import child from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
assert.equal(process.getuid(), 1000);
const status = readFileSync('/proc/self/status', 'utf8');
assert.match(status, /CapEff:\s+0+\n/);
assert.match(status, /NoNewPrivs:\s+1\n/);
assert.deepEqual(readdirSync('/sys/class/net'), ['lo']);
assert(!readdirSync('/dev').some(name => name.startsWith('nvidia') || name === 'dri'));
assert.deepEqual(readdirSync('/private'), []);
const mounts = readFileSync('/proc/self/mountinfo', 'utf8').split('\n').map(line => line.split(' '));
for (const target of ['/', '/source']) {
  const mount = mounts.find(row => row[4] === target);
  assert(mount && mount[5].split(',').includes('ro'));
}
const code = await new Promise((resolve, reject) => {
  const probe = net.createConnection({host:'1.1.1.1', port:443});
  probe.setTimeout(2000, () => {probe.destroy(); reject(Error('denial timeout'));});
  probe.once('connect', () => {probe.destroy(); reject(Error('egress possible'));});
  probe.once('error', error => {probe.destroy(); resolve(error.code);});
});
assert(['ENETUNREACH','EHOSTUNREACH','EPERM','EACCES'].includes(code));
writeFileSync('/evidence/preimport-node-unit.json', JSON.stringify({schema_version:2, status:'passed',
  scope:'unit tests only', uid:process.getuid(), code, before_repository_imports:true,
  egress_denied:true, caps:status.match(/CapEff:\s+(0+)\n/)[1], no_new_privileges:true,
  readonly_source_root_deps:true, gpu_devices:[]}));
const deny = () => {throw Error('unit sandbox denies process/network activity');};
for (const name of ['spawn','spawnSync','exec','execSync','execFile','execFileSync','fork']) child[name] = deny;
net.Socket.prototype.connect = deny;
syncBuiltinESMExports();
const {run} = await import('node:test');
const stream = run({files:['/source/request-correlation.test.mjs', '/source/manual-research.test.mjs'], isolation:'none'});
let summary;
stream.on('test:summary', data => {summary = data; console.log(JSON.stringify(data));});
stream.on('data', event => {if (event.type === 'test:fail') console.error(event.data);});
stream.on('end', () => {
  const passed = !!summary && summary.success && summary.counts.tests > 0 &&
    summary.counts.failed === 0 && summary.counts.skipped === 0;
  writeFileSync('/evidence/node-unit.pending', JSON.stringify({schema_version:2, passed,
    scope:'correlation unit tests only; no browser/build acceptance', node_version:process.version, summary}));
  renameSync('/evidence/node-unit.pending','/evidence/node-unit.json');
  process.exitCode = passed ? 0 : 1;
});
'''


def inside():
    from api import preflight, write
    preflight()
    suites = []
    # GitPython's permanent process-denial audit runs last in a fresh interpreter.
    for name in UNIT_SUITES:
        with (Path('/evidence') / (name + '.log')).open('w') as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(
                unittest.defaultTestLoader.discover(str(Path(__file__).parent), pattern=name))
        suites.append({"suite": name, "passed": result.wasSuccessful(), "tests": result.testsRun,
                       "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped)})
    passed = all(row["passed"] and row["tests"] and not row["skipped"] for row in suites)
    write("self-test.json", {"schema_version": 2, "scope": "sandbox unit tests only; no API/browser acceptance",
                             "passed": passed, "tests": sum(row["tests"] for row in suites), "suites": suites})
    return 0 if passed else 1


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-units", action="store_true", help="Also run builtin-only Node correlation tests, never build")
    parser.add_argument("--frontend-dependency-container", help="Exact stopped dependency ID for image discovery only; never mounted")
    options = parser.parse_args()
    from run import OwnedRun, compare_source, discover, docker, hash_evidence, verify_container, wait_file
    here = Path(__file__).resolve().parent
    root = here.parents[4]
    token = "arena-f0-unit-" + uuid.uuid4().hex[:10]
    output = here / ".runs" / token
    output.mkdir(parents=True)
    run = OwnedRun(output, token)
    run.proof["status"] = "failed"
    run.proof["scope"] = "sandbox unit tests only; not an API/browser acceptance proof"
    previous = {}
    def interrupted(signum, frame):
        raise InterruptedError(f"signal {signum}")
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, interrupted)
    try:
        discovery = discover(root, options.node_units, options.frontend_dependency_container) if options.frontend_dependency_container else discover(root, options.node_units)
        run.proof["discovery"] = discovery
        (output / "evidence").mkdir(mode=0o700)
        os.chown(output / "evidence", 1000, 1000)
        from confined_io import ConfinedRoot, new_destination
        with ConfinedRoot(here) as source:
            approved = (*UNIT_SOURCES, *(("browser.mjs", "request-correlation.test.mjs", "browser-manual-research.mjs", "manual-research.test.mjs") if options.node_units else ()))
            captured = {name: source.read(name) for name in approved}
        if options.node_units:
            captured["node-unit-bootstrap.mjs"] = NODE_UNITS.encode("utf-8")
        with new_destination(output / "source") as destination:
            for name, data in captured.items():
                destination.write_new(name, data)
        host = discovery["host_root"] + "/" + str(output.relative_to(root))
        run.proof["host_output"] = host
        run.proof["source_sha256"] = {name: hashlib.sha256(data).hexdigest() for name, data in captured.items()}
        (output / "source-manifest.json").write_text(json.dumps(run.proof["source_sha256"], indent=2))
        mounts = [f"type=bind,src={host}/source,dst=/source,readonly",
                  f"type=bind,src={host}/evidence,dst=/evidence"]
        cid = run.create("tests", discovery["runtime_image"], "/usr/bin/env",
                         ["-i", "HOME=/tmp", "PATH=/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE=1",
                          "/isaac-sim/python.sh", "/source/self_test.py", "--inside"], mounts)
        verify_container(run, cid, mounts)
        docker("start", cid)
        wait_file(run, cid, output / "evidence/self-test.json", timeout=30)
        result = json.loads((output / "evidence/self-test.json").read_text())
        run.proof["python_units"] = result
        assert docker("wait", cid) == "0" and result["passed"], "Python unit suites failed"
        if options.node_units:
            node = run.create("node-tests", discovery["browser_image"], "/usr/bin/env",
                              ["-i", "HOME=/tmp", "PATH=/usr/local/bin:/usr/bin:/bin",
                               "node", "/source/node-unit-bootstrap.mjs"], mounts)
            verify_container(run, node, mounts)
            docker("start", node)
            wait_file(run, node, output / "evidence/node-unit.json", timeout=30)
            result = json.loads((output / "evidence/node-unit.json").read_text())
            run.proof["node_units"] = result
            assert docker("wait", node) == "0" and result["passed"], "Node unit suites failed"
        run.proof["status"] = "passed"
    except BaseException as error:
        run.proof["failure"] = type(error).__name__ + ": " + str(error)
    finally:
        for signum in previous:
            signal.signal(signum, signal.SIG_IGN)
        try:
            if not run.cleanup():
                run.proof["status"] = "failed"
            errors = run.proof.setdefault("evidence_errors", [])
            run.proof["artifacts"] = {}
            try:
                from confined_io import read_confined
                manifest = run.proof["source_sha256"]
                changed, rejected = compare_source(output / "source", manifest)
                run.proof["staged_source_unchanged"] = bool(manifest) and not changed
                run.proof["staged_source_hash_errors"] = rejected
                errors.extend(changed)
                hash_evidence(output, run.proof["artifacts"], errors)
                run.proof["artifacts"]["source-manifest.json"] = hashlib.sha256(read_confined(output, "source-manifest.json")).hexdigest()
            except Exception as error:
                errors.append(type(error).__name__)
            if errors:
                run.proof["status"] = "failed"
            run.save()
            run.proof["artifacts"]["ownership.json"] = hashlib.sha256(read_confined(output, "ownership.json")).hexdigest()
            (output / "run-proof.json").write_text(json.dumps(run.proof, indent=2))
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    print(json.dumps({"status": run.proof["status"], "output": str(output),
                      "remaining_owned": run.proof["remaining_owned"], "failure": run.proof.get("failure")}))
    return 0 if run.proof["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(inside() if "--inside" in sys.argv else main())
