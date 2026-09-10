declare const __dirname: string;
const fs = jest.requireActual('node:fs');
const path = jest.requireActual('node:path');
const os = jest.requireActual('node:os');
const cp = jest.requireActual('node:child_process');
const createRequire = jest.requireActual('node:module').createRequire;
const root = path.resolve(__dirname, '..');
const nativeRequire = createRequire(path.join(root, 'package.json'));
const modules = path.dirname(path.dirname(nativeRequire.resolve('expo/package.json')));

it('the documented doctor command fails when the real Expo config aborts before checks', () => {
  const isolated = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'hypertodo-doctor-')));
  try {
    fs.copyFileSync(path.join(root, 'app.config.ts'), path.join(isolated, 'app.config.ts'));
    fs.copyFileSync(path.join(root, 'package.json'), path.join(isolated, 'package.json'));
    const script = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).scripts.doctor;
    const args = script === 'expo-doctor'
      ? [nativeRequire.resolve('expo-doctor/bin/expo-doctor.js'), '--verbose']
      : [path.join(root, 'scripts/doctor.cjs'), isolated];
    expect(['expo-doctor', 'node scripts/doctor.cjs']).toContain(script);
    const result = cp.spawnSync(process.execPath, args, {cwd: isolated, encoding: 'utf8', timeout: 20000,
      env: {PATH: path.dirname(process.execPath) + path.delimiter + '/usr/bin:/bin',
        NODE_PATH: modules, HOME: isolated, TMPDIR: isolated, EXPO_HOME: isolated,
        EXPO_NO_DOTENV: '1', EXPO_NO_TELEMETRY: '1', CI: '1', NO_COLOR: '1'}});
    expect(result.error).toBeUndefined();
    expect(result.signal).toBeNull();
    expect(result.status).not.toBe(0);
    expect(result.stdout + result.stderr).not.toMatch(/\d+\/\d+ checks passed\. No issues detected!/);
  } finally { fs.rmSync(isolated, {recursive: true, force: true}); }
}, 30000);

const configResult = () => ({status: 0, signal: null, stdout: JSON.stringify({exp: {sdkVersion: '57.0.0'}, pkg: {name: 'hypertodo-mobile'}}), stderr: ''});
const doctorResult = (stdout: string, status = 0) => ({status, signal: null, stdout, stderr: ''});
const successfulReport = 'Running 2 checks on your project...\n✔ Check config\n✔ Check packages\n2/2 checks passed. No issues detected!\n';
function runWith(results: any[]) {
  const spawn = jest.fn(() => results.shift());
  const diagnostics: string[] = [];
  const result = jest.requireActual('../scripts/doctor.cjs').runDoctor({projectRoot: root, spawn, write: (_channel: string, value: string) => diagnostics.push(value)});
  return {result, spawn, diagnostics: diagnostics.join('')};
}

it('propagates configuration failure and never launches Doctor afterward', () => {
  const value = runWith([{status: 1, signal: null, stdout: '', stderr: 'configuration failed'}]);
  expect(value.result).toMatchObject({ok: false, stage: 'config'});
  expect(value.spawn).toHaveBeenCalledTimes(1);
  expect(value.diagnostics).toContain('configuration failed');
});

it('requires the actual complete locked-version success report, not exit zero alone', () => {
  for (const report of ['', 'Error: expo config failed\n', '2/2 checks passed. No issues detected!\n',
    '✔ Check config\n1/2 checks passed. 1 checks failed.\n',
    '✔ Check config\n2/2 checks passed. No issues detected!\n',
    '✔ Duplicate\n✔ Duplicate\n2/2 checks passed. No issues detected!\n',
    successfulReport + '2/2 checks passed. No issues detected!\n']) {
    expect(runWith([configResult(), doctorResult(report)]).result).toMatchObject({ok: false, stage: 'report'});
  }
});

it('accepts complete successful check records and preserves full Doctor diagnostics', () => {
  const value = runWith([configResult(), doctorResult(successfulReport)]);
  expect(value.result).toEqual({ok: true, checks: 2, exitCode: 0});
  expect(value.diagnostics).toContain(successfulReport);
  expect(value.spawn.mock.calls[0]).toHaveLength(3);
  expect((value.spawn.mock.calls as any)[0][1].slice(-3)).toEqual(['config', '--json', '--full']);
  expect((value.spawn.mock.calls as any)[1][1].slice(-1)).toEqual(['--verbose']);
});

it('distinguishes launch, timeout, signal, invalid config and failed checks without passing them', () => {
  for (const [result, stage] of [
    [{status: null, signal: null, error: {code: 'ENOENT'}, stdout: '', stderr: ''}, 'launch'],
    [{status: null, signal: 'SIGTERM', error: {code: 'ETIMEDOUT'}, stdout: '', stderr: ''}, 'timeout'],
    [{status: null, signal: 'SIGTERM', stdout: '', stderr: ''}, 'signal'],
    [{status: 0, signal: null, stdout: '{}', stderr: ''}, 'config']
  ] as const) expect(runWith([result]).result).toMatchObject({ok: false, stage});
  expect(runWith([configResult(), doctorResult('✖ Failed check\n', 1)]).result).toMatchObject({ok: false, stage: 'checks'});
  expect(runWith([configResult(), {...doctorResult(''), status: null, error: {code: 'ETIMEDOUT'}}]).result).toMatchObject({ok: false, stage: 'timeout'});
});
