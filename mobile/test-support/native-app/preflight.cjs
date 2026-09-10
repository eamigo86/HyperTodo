'use strict';
const {output}=require('../portable-paths.cjs');

const fail = code => {
  throw new Error(`native-app-preflight:${code}`);
};
const FIELDS = ['run', 'apiOrigin', 'metroOrigin', 'credentialKey', 'themeKey'];
/** Validate fresh namespaces; hostname resolution/private interface is verified separately. */
function validateFixtureConfig(config) {
  if (!config || Object.keys(config).length !== FIELDS.length || !FIELDS.every(key => Object.hasOwn(config, key)) || !/^[a-f0-9]{32}$/.test(config.run)) fail('config');
  for (const [key, prefix] of [['apiOrigin', 'hvt'], ['metroOrigin', 'hvtm']]) {
    let url;
    try {
      url = new URL(config[key]);
    } catch {
      fail('origin');
    }
    if (url.protocol !== 'http:' || url.hostname !== `${prefix}-${config.run}.local` || url.origin !== config[key] || url.username || url.password || !url.port || url.port === '8081') fail('origin');
  }
  if (config.credentialKey !== `hvt-native-${config.run}.credential` || config.themeKey !== `hvt-native-${config.run}.theme`) fail('storage');
  return Object.freeze({
    ...config
  });
}
function expectedConfig(expected) {
  if (!expected || !['ios', 'android'].includes(expected.platform) || !expected.username || expected.username === 'anonymous' || !/^hypertodo-native-app(?:-[a-z0-9-]+)?$/.test(expected.slug) || expected.mainModuleName !== 'index') fail('expectations');
  try { output(expected); } catch { fail('expectations'); }
  return validateFixtureConfig(Object.fromEntries(FIELDS.map(key => [key, expected[key]])));
}
/** Inspect the actual served manifest against independently supplied expectations. */
function validateServedManifest(manifest, expected) {
  const config = expectedConfig(expected),
    go = manifest?.extra?.expoGo,
    client = manifest?.extra?.expoClient;
  if (!go || !client || !manifest.launchAsset) fail('manifest');
  if (!/^57\.\d+\.\d+$/.test(client.sdkVersion)) fail('sdk');
  if (go.username !== expected.username) fail('account');
  if (go.developer?.projectRoot !== expected.projectRoot || client.slug !== expected.slug || go.mainModuleName !== 'index') fail('source');
  let asset;
  try {
    asset = new URL(manifest.launchAsset.url);
  } catch {
    fail('asset');
  }
  if (asset.origin !== config.metroOrigin || asset.pathname !== '/index.bundle' || asset.username || asset.password || asset.hash || asset.searchParams.get('platform') !== expected.platform || asset.searchParams.get('dev') !== 'true' || go.debuggerHost !== new URL(config.metroOrigin).host || client.hostUri !== new URL(config.metroOrigin).host) fail('asset');
  const actual = validateFixtureConfig(client.extra?.nativeApp);
  if (FIELDS.some(key => actual[key] !== config[key])) fail('config');
  return Object.freeze({
    ready: true,
    scope: 'served-real-app-manifest-only',
    native: 'NOT_RUN'
  });
}
/** HTTP200 is necessary; source strings supplement independently frozen entry provenance. */
function validateDevelopmentJavaScript(result, expected) {
  expectedConfig(expected);
  if (result?.status !== 200 || typeof result.contentType !== 'string' || !/javascript/i.test(result.contentType) || typeof result.source !== 'string' || result.source.length > 32 * 1024 * 1024) fail('javascript');
  for (const marker of ['realtime-native-app-v1', 'createSessionApp', 'createSessionCredentialPort', 'createThemeStore', 'createOwnedNativePorts', 'expo/src/async-require/hmr.ts']) if (!result.source.includes(marker)) fail('javascript');
  return Object.freeze({
    ready: true,
    scope: 'development-js-only',
    native: 'NOT_RUN'
  });
}
module.exports = {
  validateExpectations: expectedConfig,
  validateFixtureConfig,
  validateServedManifest,
  validateDevelopmentJavaScript
};
