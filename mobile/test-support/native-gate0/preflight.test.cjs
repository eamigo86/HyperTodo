'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { validateServedManifest } = require('./preflight.cjs');

const expected = {
  username: 'synthetic-account',
  projectRoot: '/private/tmp/isolated-native-fixture/app',
  slug: 'synthetic-native-fixture',
  mainModuleName: 'index',
  metroOrigin: 'http://192.168.4.43:8082',
  probeUrl: 'http://192.168.4.43:8787/probe-0123456789abcdef0123456789abcdef',
};
function manifest() {
  return {
    launchAsset: { url: `${expected.metroOrigin}/index.bundle?platform=ios&dev=true` },
    extra: {
      expoGo: {
        username: expected.username, developer: { projectRoot: expected.projectRoot },
        mainModuleName: 'index', debuggerHost: '192.168.4.43:8082',
      },
      expoClient: {
        sdkVersion: '57.0.0', slug: expected.slug, hostUri: '192.168.4.43:8082',
        extra: { gate0BaseUrl: expected.probeUrl },
      },
    },
  };
}

test('accepts only the observed matching manifest without mutating identity or claiming native PASS', () => {
  const actual = manifest();
  const before = structuredClone(actual);
  const result = validateServedManifest(actual, expected);
  assert.equal(result.ready, true);
  assert.equal(result.scope, 'served-manifest-only');
  assert.equal(result.nativeIo, 'NOT_RUN');
  assert.deepEqual(actual, before);
  assert.ok(!JSON.stringify(result).includes(expected.username));
  assert.ok(!JSON.stringify(result).includes(expected.probeUrl));
});

for (const username of [undefined, '', ' ', 'anonymous', 'different-account']) {
  test(`rejects missing or mismatched served account: ${JSON.stringify(username)}`, () => {
    const actual = manifest();
    actual.extra.expoGo.username = username;
    assert.throws(() => validateServedManifest(actual, expected), /account-mismatch/);
  });
}

const mismatches = [
  ['sdk-mismatch', value => { value.extra.expoClient.sdkVersion = '56.0.0'; }],
  ['project-mismatch', value => { value.extra.expoGo.developer.projectRoot = '/original/mobile'; }],
  ['project-mismatch', value => { value.extra.expoClient.slug = 'production'; }],
  ['entry-mismatch', value => { value.extra.expoGo.mainModuleName = 'App'; }],
  ['entry-mismatch', value => { value.launchAsset.url = `${expected.metroOrigin}/App.bundle`; }],
  ['origin-mismatch', value => { value.extra.expoGo.debuggerHost = '192.168.4.43:8081'; }],
  ['origin-mismatch', value => { value.extra.expoClient.hostUri = '192.168.4.43:8081'; }],
  ['origin-mismatch', value => { value.launchAsset.url = 'http://example.com/index.bundle'; }],
  ['probe-mismatch', value => { value.extra.expoClient.extra.gate0BaseUrl = `${expected.probeUrl}0`; }],
];
for (const [code, mutate] of mismatches) {
  test(`rejects ${code} rather than repairing the manifest: ${mutate.toString()}`, () => {
    const actual = manifest();
    mutate(actual);
    const before = structuredClone(actual);
    assert.throws(() => validateServedManifest(actual, expected), new RegExp(code));
    assert.deepEqual(actual, before);
  });
}

test('rejects config-only input and missing independent expectations', () => {
  assert.throws(() => validateServedManifest({ sdkVersion: '57.0.0' }, expected), /invalid-manifest/);
  for (const change of [
    { username: '' }, { username: 'anonymous' }, { projectRoot: '' },
    { metroOrigin: 'http://example.com:8082' },
    { probeUrl: 'http://192.168.4.99:8787/probe-0123456789abcdef0123456789abcdef' },
  ]) assert.throws(() => validateServedManifest(manifest(), { ...expected, ...change }), /invalid-expectations/);
});

test('diagnostics contain fixed codes, not accounts, URLs or raw malformed values', () => {
  const actual = manifest();
  actual.extra.expoGo.username = 'private-value-not-for-logs';
  assert.throws(() => validateServedManifest(actual, expected), error => {
    assert.equal(error.message, 'native preflight: account-mismatch');
    assert.ok(!String(error).includes('private-value'));
    return true;
  });
});

test('CLI checks a saved manifest and emits only a sanitized verdict', t => {
  const fs = require('node:fs');
  const path = require('node:path');
  const { spawnSync } = require('node:child_process');
  const dir = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'djhv-manifest-test-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'synthetic-manifest.json');
  const env = { ...process.env,
    NATIVE_EXPECTED_EXPO_USERNAME: expected.username,
    NATIVE_EXPECTED_PROJECT_ROOT: expected.projectRoot,
    NATIVE_EXPECTED_SLUG: expected.slug,
    NATIVE_EXPECTED_METRO_ORIGIN: expected.metroOrigin,
    NATIVE_PROBE_BASE_URL: expected.probeUrl,
  };
  fs.writeFileSync(file, JSON.stringify(manifest()));
  const run = () => spawnSync(process.execPath, [require.resolve('./preflight.cjs'), file], { env, encoding: 'utf8', timeout: 2000 });
  let result = run();
  assert.equal(result.status, 0);
  assert.equal(JSON.parse(result.stdout).nativeIo, 'NOT_RUN');
  assert.equal(result.stderr, '');
  const anonymous = manifest();
  delete anonymous.extra.expoGo.username;
  fs.writeFileSync(file, JSON.stringify(anonymous));
  result = run();
  assert.equal(result.status, 1);
  assert.equal(result.stdout, '');
  assert.equal(result.stderr, 'native preflight: account-mismatch\n');
  fs.writeFileSync(file, 'raw-sensitive-invalid-json');
  result = run();
  assert.equal(result.status, 1);
  assert.equal(result.stderr, 'native preflight: unreadable-manifest\n');
});

for (const platform of ['ios', 'android']) {
  test(`requires the independently expected ${platform} development asset`, () => {
    const actual = manifest();
    actual.launchAsset.url = `${expected.metroOrigin}/index.bundle?platform=${platform}&dev=true`;
    assert.equal(validateServedManifest(actual, { ...expected, platform }).nativeIo, 'NOT_RUN');
    const wrong = platform === 'ios' ? 'android' : 'ios';
    actual.launchAsset.url = `${expected.metroOrigin}/index.bundle?platform=${wrong}&dev=true`;
    assert.throws(() => validateServedManifest(actual, { ...expected, platform }), /platform-mismatch/);
  });
}
for (const platform of ['web', '', null]) test(`rejects unsupported expected platform ${JSON.stringify(platform)}`, () => {
  assert.throws(() => validateServedManifest(manifest(), { ...expected, platform }), /invalid-expectations/);
});
test('rejects a missing or ambiguous served platform rather than counting iOS readiness as Android', () => {
  for (const query of ['dev=true', 'platform=android&platform=ios&dev=true']) {
    const actual = manifest(); actual.launchAsset.url = `${expected.metroOrigin}/index.bundle?${query}`;
    assert.throws(() => validateServedManifest(actual, { ...expected, platform: 'android' }), /platform-mismatch/);
  }
});
test('development target takes explicit portable project and fresh private interface, not historical defaults',()=>{
  const {developmentTarget}=require('./preflight.cjs');
  const env={NATIVE_METRO_ORIGIN:'http://192.168.45.12:8092',NATIVE_EXPECTED_PROJECT_ROOT:'/owned/isolated/app',NATIVE_EXPECTED_SLUG:'fresh-native-probe',NATIVE_EXPECTED_PLATFORM:'android'};
  assert.deepEqual(developmentTarget(env),{origin:env.NATIVE_METRO_ORIGIN,projectRoot:env.NATIVE_EXPECTED_PROJECT_ROOT,slug:env.NATIVE_EXPECTED_SLUG,platform:'android'});
  for(const change of [{NATIVE_EXPECTED_PROJECT_ROOT:undefined},{NATIVE_EXPECTED_SLUG:undefined},{NATIVE_METRO_ORIGIN:'http://0.0.0.0:8092'},{NATIVE_METRO_ORIGIN:'http://192.168.45.12:8081'},{NATIVE_METRO_ORIGIN:'http://192.168.45.12:8092/path'},{NATIVE_EXPECTED_PROJECT_ROOT:'relative/app'}]) assert.throws(()=>developmentTarget({...env,...change}));
});
