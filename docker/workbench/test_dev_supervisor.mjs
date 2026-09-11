// Copyright (c) 2026, The Isaac Lab-Arena Project Developers.
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { test } from 'node:test';

const moduleUrl = new URL('./dev-supervisor.mjs', import.meta.url);
test('service failure tears down the other service and reports failure', async () => {
  const code = `import { supervise } from ${JSON.stringify(moduleUrl.href)};
    process.exitCode = await supervise([[process.execPath, '-e', 'setTimeout(()=>process.exit(7),50)'],
      [process.execPath, '-e', 'console.log(process.pid);setInterval(()=>{},1000)']]);`;
  const supervisor = spawn(process.execPath, ['--input-type=module', '-e', code], { stdio: ['ignore', 'pipe', 'inherit'] });
  let output = '';
  supervisor.stdout.on('data', chunk => { output += chunk; });
  const [exitCode] = await new Promise(resolve => supervisor.once('exit', (...args) => resolve(args)));
  assert.equal(exitCode, 7);
  assert.throws(() => process.kill(Number(output.trim()), 0), { code: 'ESRCH' });
});

test('supervisor forwards termination and reaps both service groups', async () => {
  assert.ok(existsSync(moduleUrl), 'development supervisor missing');
  const childCode = 'console.log(process.pid); setInterval(()=>{},1000)';
  const code = `import { supervise } from ${JSON.stringify(moduleUrl.href)};
    process.exitCode = await supervise([[process.execPath, '-e', ${JSON.stringify(childCode)}],
                                       [process.execPath, '-e', ${JSON.stringify(childCode)}]]);`;
  const supervisor = spawn(process.execPath, ['--input-type=module', '-e', code], { stdio: ['ignore', 'pipe', 'inherit'] });
  const pids = [];
  let buffer = '';
  const timeout = setTimeout(() => supervisor.kill('SIGKILL'), 5000);
  supervisor.stdout.on('data', chunk => {
    buffer += chunk;
    const lines = buffer.split('\n'); buffer = lines.pop();
    pids.push(...lines.filter(Boolean).map(Number));
    if (pids.length === 2) supervisor.kill('SIGTERM');
  });
  const [exitCode] = await new Promise(resolve => supervisor.once('exit', (...args) => resolve(args)));
  clearTimeout(timeout);
  assert.equal(exitCode, 143);
  assert.equal(pids.length, 2);
  for (const pid of pids) assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
});
