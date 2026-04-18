#!/usr/bin/env node

const { spawnSync } = require('child_process');

process.env.CI = 'true';

const testScript = require.resolve('react-scripts/scripts/test');
const result = spawnSync(process.execPath, [testScript, ...process.argv.slice(2)], {
  stdio: 'inherit',
  env: process.env,
});

if (result.error) {
  throw result.error;
}

if (result.signal) {
  process.kill(process.pid, result.signal);
}

process.exit(result.status ?? 1);
