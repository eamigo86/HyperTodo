'use strict';

const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const DOCTOR_VERSION = '1.20.4';

// Public --verbose output of the locked version: one record per check followed
// by exactly one terminal success summary. Exit zero alone is not acceptance.
function successfulReport(stdout) {
  const text = stdout.replace(/\x1b\[[0-9;]*m/g, '').replace(/\r/g, '').trim();
  const summaries = [...text.matchAll(/^(\d+)\/(\d+) checks passed\. No issues detected!$/gm)];
  const records = [...text.matchAll(/^✔ ([^\n]+)$/gm)].map(match => match[1].trim());
  if (summaries.length !== 1 || text.split('\n').at(-1) !== summaries[0][0] || /^✖ /m.test(text)) return null;
  const passed = Number(summaries[0][1]), total = Number(summaries[0][2]);
  if (!Number.isSafeInteger(total) || total < 1 || passed !== total || records.length !== total || new Set(records).size !== total || records.some(record => !record)) return null;
  return total;
}

function runDoctor({projectRoot = path.resolve(__dirname, '..'), spawn = spawnSync,
  write = (channel, value) => process[channel].write(value)} = {}) {
  const fail = (stage, detail) => {
    write('stderr', `doctor-quality: ${stage} failed (${detail}).\n`);
    return {ok: false, stage, detail, exitCode: 1};
  };
  let expo, doctor;
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(projectRoot, 'package.json'), 'utf8'));
    const metadata = require.resolve('expo-doctor/package.json', {paths: [projectRoot]});
    const installed = JSON.parse(fs.readFileSync(metadata, 'utf8'));
    if (pkg.devDependencies?.['expo-doctor'] !== DOCTOR_VERSION || installed.version !== DOCTOR_VERSION) return fail('version', 'unsupported-report-contract');
    expo = require.resolve('expo/bin/cli', {paths: [projectRoot]});
    doctor = path.join(path.dirname(metadata), 'bin/expo-doctor.js');
  } catch { return fail('launch', 'missing-tool-or-package-metadata'); }
  const env = {...process.env, PATH: path.dirname(process.execPath) + path.delimiter + (process.env.PATH || '')};
  const invoke = (args, phase, timeout) => {
    let result;
    try { result = spawn(process.execPath, args, {cwd: projectRoot, env, encoding: 'utf8', timeout, maxBuffer: 4 * 1024 * 1024}); }
    catch { return fail('launch', phase); }
    const stdout = result?.stdout || '', stderr = result?.stderr || '';
    // Successful config JSON stays private; all failure/Doctor diagnostics remain
    // available to the caller rather than being reduced to a shell exit code.
    if (phase === 'doctor' || result?.status !== 0) write('stdout', stdout);
    write('stderr', stderr);
    if (result?.error?.code === 'ETIMEDOUT') return fail('timeout', phase);
    if (result?.error || !result) return fail('launch', phase);
    if (result.signal) return fail('signal', phase);
    if (result.status !== 0) return fail(phase === 'config' ? 'config' : 'checks', 'nonzero-exit');
    return {ok: true, stdout};
  };
  const config = invoke([expo, 'config', '--json', '--full'], 'config', 30000);
  if (!config.ok) return config;
  try {
    const parsed = JSON.parse(config.stdout);
    if (!parsed.exp || !parsed.pkg || typeof parsed.exp.sdkVersion !== 'string') return fail('config', 'invalid-full-config');
  } catch { return fail('config', 'invalid-json'); }
  const result = invoke([doctor, '--verbose'], 'doctor', 180000);
  if (!result.ok) return result;
  const checks = successfulReport(result.stdout);
  return checks === null ? fail('report', 'missing-or-incomplete-success') : {ok: true, checks, exitCode: 0};
}

module.exports = {runDoctor, successfulReport};
if (require.main === module) {
  if (process.argv.length > 3) {
    process.stderr.write('doctor-quality: usage: node scripts/doctor.cjs [project-root]\n');
    process.exitCode = 1;
  } else process.exitCode = runDoctor({projectRoot: process.argv[2] ? path.resolve(process.argv[2]) : undefined}).exitCode;
}
