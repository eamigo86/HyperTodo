'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const {developmentTarget}=require('./preflight.cjs');

// Explicit development HTTP acceptance; start the isolated fixture first.
// Never fetch a bootstrap/stream endpoint and never launch a native client.
test('isolated Expo serves development JavaScript for the expected native platform including HMR', async () => {
  const {platform,origin,projectRoot,slug}=developmentTarget(process.env);
  const manifestResponse = await fetch(origin, {
    headers:{'expo-platform':platform,Accept:'application/expo+json,application/json'},
    redirect:'error',signal:AbortSignal.timeout(15000),
  });
  assert.equal(manifestResponse.status, 200);
  const manifest = await manifestResponse.json();
  assert.equal(manifest.extra.expoClient.slug, slug);
  assert.equal(manifest.extra.expoGo.mainModuleName, 'index');
  assert.equal(manifest.extra.expoGo.developer.projectRoot, projectRoot);
  const asset = new URL(manifest.launchAsset.url);
  assert.equal(asset.origin, origin);
  assert.equal(asset.pathname, '/index.bundle');
  assert.equal(asset.searchParams.get('dev'), 'true');
  assert.equal(asset.searchParams.get('platform'), platform);
  const response = await fetch(asset, {redirect:'error',signal:AbortSignal.timeout(120000)});
  const source = await response.text();
  if (response.status !== 200) {
    // Report only a known resolver symptom, never arbitrary URLs/account metadata.
    assert.fail(`Development JavaScript HTTP${response.status}; HMR replacement failure=${source.includes('Failed to replace react-native/Libraries/Utilities/HMRClient.js')}`);
  }
  assert.match(response.headers.get('content-type'), /javascript/);
  assert.ok(source.includes('Run isolated native I/O probe'), 'Standalone fixture UI must be present');
  assert.ok(source.includes('expo/src/async-require/hmr.ts'), 'Real Expo HMR implementation must remain enabled');
  assert.ok(!source.includes('src/biometrics'), 'HyperTodo production App must not enter this graph');
});
