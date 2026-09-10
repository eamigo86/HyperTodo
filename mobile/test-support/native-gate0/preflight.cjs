'use strict';

const { isIP } = require('node:net');
const { isAbsolute } = require('node:path');

class PreflightError extends Error {
  constructor(code) { super(`native preflight: ${code}`); }
}
const fail = code => { throw new PreflightError(code); };
const nonempty = value => typeof value === 'string' && value.length > 0 && value.trim() === value;
function privateHttpUrl(value) {
  let url;
  try { url = new URL(value); } catch { fail('invalid-expectations'); }
  const [a, b] = url.hostname.split('.').map(Number);
  if (url.protocol !== 'http:' || url.username || url.password || url.search || url.hash
      || isIP(url.hostname) !== 4
      || !(a === 10 || a === 127 || (a === 192 && b === 168) || (a === 172 && b >= 16 && b <= 31))) {
    fail('invalid-expectations');
  }
  return url;
}
/** Explicit inputs for the optional served-development check; no HTTP here. */
function developmentTarget(env) {
  const origin=env.NATIVE_METRO_ORIGIN,projectRoot=env.NATIVE_EXPECTED_PROJECT_ROOT,slug=env.NATIVE_EXPECTED_SLUG,platform=env.NATIVE_EXPECTED_PLATFORM??'ios';
  const url=privateHttpUrl(origin);
  if(url.origin!==origin || !url.port || Number(url.port)<1024 || url.port==='8081' ||
    !nonempty(projectRoot) || !isAbsolute(projectRoot) || !nonempty(slug) || !['ios','android'].includes(platform)) fail('invalid-expectations');
  return {origin,projectRoot,slug,platform};
}

/** Inspect served data only; expectations must come independently from the coordinator. */
function validateServedManifest(manifest, expected) {
  if (!expected || !['username', 'projectRoot', 'slug', 'mainModuleName', 'metroOrigin', 'probeUrl'].every(key => nonempty(expected[key]))
      || expected.username === 'anonymous' || !isAbsolute(expected.projectRoot)
      || expected.mainModuleName !== 'index') fail('invalid-expectations');
  const platform = expected.platform === undefined ? 'ios' : expected.platform;
  if (!['ios', 'android'].includes(platform)) fail('invalid-expectations');
  const metro = privateHttpUrl(expected.metroOrigin);
  const probe = privateHttpUrl(expected.probeUrl);
  if (metro.origin !== expected.metroOrigin || probe.hostname !== metro.hostname
      || !/^\/probe-[a-f0-9]{32}$/.test(probe.pathname)) fail('invalid-expectations');
  const go = manifest?.extra?.expoGo;
  const client = manifest?.extra?.expoClient;
  if (!go || !client || !manifest.launchAsset) fail('invalid-manifest');
  if (typeof client.sdkVersion !== 'string' || !/^57\.\d+\.\d+$/.test(client.sdkVersion)) fail('sdk-mismatch');
  if (go.developer?.projectRoot !== expected.projectRoot || client.slug !== expected.slug) fail('project-mismatch');
  if (go.mainModuleName !== expected.mainModuleName) fail('entry-mismatch');
  let asset;
  try { asset = new URL(manifest.launchAsset.url); } catch { fail('entry-mismatch'); }
  if (asset.origin !== metro.origin || asset.username || asset.password
      || go.debuggerHost !== metro.host || client.hostUri !== metro.host) fail('origin-mismatch');
  if (asset.pathname !== `/${expected.mainModuleName}.bundle`) fail('entry-mismatch');
  if (asset.searchParams.getAll('platform').length !== 1 || asset.searchParams.get('platform') !== platform) fail('platform-mismatch');
  if (!nonempty(go.username) || go.username !== expected.username) fail('account-mismatch');
  if (client.extra?.gate0BaseUrl !== expected.probeUrl) fail('probe-mismatch');
  return Object.freeze({ ready: true, scope: 'served-manifest-only', nativeIo: 'NOT_RUN' });
}

/** Offline file inspection only: never reads Expo credentials or launches a server. */
function main() {
  if (process.argv.length !== 3) fail('unreadable-manifest');
  const fs = require('node:fs');
  let manifest;
  try {
    if (fs.statSync(process.argv[2]).size > 1024 * 1024) fail('unreadable-manifest');
    manifest = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  } catch { fail('unreadable-manifest'); }
  const result = validateServedManifest(manifest, {
    platform: process.env.NATIVE_EXPECTED_PLATFORM,
    username: process.env.NATIVE_EXPECTED_EXPO_USERNAME,
    projectRoot: process.env.NATIVE_EXPECTED_PROJECT_ROOT,
    slug: process.env.NATIVE_EXPECTED_SLUG,
    mainModuleName: 'index',
    metroOrigin: process.env.NATIVE_EXPECTED_METRO_ORIGIN,
    probeUrl: process.env.NATIVE_PROBE_BASE_URL,
  });
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

module.exports = { validateServedManifest, developmentTarget };
if (require.main === module) {
  try { main(); } catch (error) {
    process.stderr.write(`${error instanceof PreflightError ? error.message : 'native preflight: invalid-manifest'}\n`);
    process.exitCode = 1;
  }
}
