'use strict';

const test = require('node:test'),
  assert = require('node:assert/strict');
const {
  launcherFiles,
  validateEntry
} = require('./launcher.cjs');
const run = 'a'.repeat(32),
  root = require('node:path').join(require('node:fs').realpathSync(require('node:os').tmpdir()), `native-app-${run}`, 'metro');
const expected = {
  run,
  apiOrigin: `http://hvt-${run}.local:8787`,
  metroOrigin: `http://hvtm-${run}.local:8082`,
  credentialKey: `hvt-native-${run}.credential`,
  themeKey: `hvt-native-${run}.theme`,
  platform: 'ios',
  username: 'fixture-account',
  projectRoot: root,
  slug: 'hypertodo-native-app',
  mainModuleName: 'index'
};
const modules = require('node:path').resolve(__dirname, '../../node_modules');
test('prepares only separate real entry/config with readonly deps and real Expo HMR', () => {
  const files = launcherFiles(expected, modules);
  assert.deepEqual(Object.keys(files).sort(), ['app.config.cjs', 'babel.config.cjs', 'index.js', 'metro.config.cjs', 'package.json'].sort());
  assert.match(files['index.js'], /test-support\/native-app\/index.tsx/);
  assert.doesNotMatch(files['index.js'], /native-gate0\/index|DefaultApp/);
  assert.match(files['metro.config.cjs'], /withSharedExpo/);
  assert.ok(files['metro.config.cjs'].includes(require('node:path').resolve(__dirname, '../..')));
  assert.match(files['metro.config.cjs'], /useWatchman = false/);
  assert.ok(!Object.values(files).some(value => value.includes(expected.username)));
  assert.ok(validateEntry(files['index.js']));
  assert.throws(() => validateEntry('require("../../App")'), /entry-provenance/);
});
test('rejects source/default storage drift before making launcher content', () => {
  assert.throws(() => launcherFiles({
    ...expected,
    credentialKey: 'hypertodo.biometric.token'
  }, modules));
  assert.throws(() => launcherFiles({
    ...expected,
    projectRoot: '/Users/original'
  }, modules));
});
