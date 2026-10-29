// Copyright (c) 2026, The Isaac Lab-Arena Project Developers.
// SPDX-License-Identifier: Apache-2.0
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

/** Forward signals to owned service groups and wait for every direct child. */
export async function supervise(commands, { once = false } = {}) {
  const children = new Set();
  let stopping = false;
  let result = 0;
  let timer;
  const signalGroup = (child, signal) => {
    try { process.kill(-child.pid, signal); }
    catch (error) { if (error.code !== 'ESRCH') throw error; }
  };
  const shutdown = code => {
    if (stopping) return;
    stopping = true;
    result = code;
    for (const child of children) signalGroup(child, 'SIGTERM');
    timer = setTimeout(() => {
      for (const child of children) signalGroup(child, 'SIGKILL');
    }, 5000);
    timer.unref();
  };
  const terminate = () => shutdown(143);
  const interrupt = () => shutdown(130);
  process.on('SIGTERM', terminate);
  process.on('SIGINT', interrupt);
  try {
    await Promise.all(commands.map(([command, ...args]) => new Promise(resolve => {
      const child = spawn(command, args, { stdio: 'inherit', detached: true });
      children.add(child);
      child.once('error', error => {
        console.error(`workbench service failed: ${error.message}`);
        children.delete(child);
        shutdown(1);
        resolve();
      });
      child.once('exit', (code, signal) => {
        children.delete(child);
        if (!stopping) shutdown(once && code === 0 && !signal ? 0 : (code || 1));
        resolve();
      });
    })));
  } finally {
    clearTimeout(timer);
    process.off('SIGTERM', terminate);
    process.off('SIGINT', interrupt);
  }
  return result;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  // The image includes Node, npm and npx; dependencies live only in a named volume.
  const installed = await supervise([['npm', 'ci', '--cache', '/tmp/npm-cache']], { once: true });
  process.exitCode = installed || await supervise([
    ['nginx', '-e', '/dev/stderr', '-g', 'daemon off;'],
    ['node', '/app/node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5173', '--strictPort'],
  ]);
}
