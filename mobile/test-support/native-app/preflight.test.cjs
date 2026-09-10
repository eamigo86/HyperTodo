'use strict';

const test = require('node:test'),
  assert = require('node:assert/strict');
const {
  validateServedManifest,
  validateDevelopmentJavaScript,
  validateFixtureConfig
} = require('./preflight.cjs');
const run = 'a'.repeat(32),
  apiOrigin = `http://hvt-${run}.local:8787`,
  metroOrigin = `http://hvtm-${run}.local:8082`;
const config = {
  run,
  apiOrigin,
  metroOrigin,
  credentialKey: `hvt-native-${run}.credential`,
  themeKey: `hvt-native-${run}.theme`
};
const expected = {
  ...config,
  platform: 'ios',
  username: 'fixture-account',
  projectRoot: require('node:path').join(require('node:fs').realpathSync(require('node:os').tmpdir()), `native-app-${run}`, 'metro'),
  slug: 'hypertodo-native-app',
  mainModuleName: 'index'
};
function manifest() {
  return {
    launchAsset: {
      url: `${metroOrigin}/index.bundle?platform=ios&dev=true`
    },
    extra: {
      expoGo: {
        username: expected.username,
        mainModuleName: 'index',
        debuggerHost: new URL(metroOrigin).host,
        developer: {
          projectRoot: expected.projectRoot
        }
      },
      expoClient: {
        sdkVersion: '57.0.0',
        slug: expected.slug,
        hostUri: new URL(metroOrigin).host,
        extra: {
          nativeApp: config
        }
      }
    }
  };
}
const js = 'realtime-native-app-v1 createSessionApp createSessionCredentialPort createThemeStore createOwnedNativePorts expo/src/async-require/hmr.ts';
test('accepts independently matched actual App manifest/DI and distinct fresh host aliases', () => {
  assert.ok(Object.isFrozen(validateFixtureConfig(config)));
  assert.deepEqual(validateServedManifest(manifest(), expected), {
    ready: true,
    scope: 'served-real-app-manifest-only',
    native: 'NOT_RUN'
  });
  assert.deepEqual(validateDevelopmentJavaScript({
    status: 200,
    contentType: 'application/javascript',
    source: js
  }, expected), {
    ready: true,
    scope: 'development-js-only',
    native: 'NOT_RUN'
  });
});
for (const [name, modify] of Object.entries({
  staleAPI: m => {
    m.extra.expoClient.extra.nativeApp = {
      ...config,
      apiOrigin: 'http://127.0.0.1:8000'
    };
  },
  defaultStorage: m => {
    m.extra.expoClient.extra.nativeApp = {
      ...config,
      credentialKey: 'hypertodo.biometric.token'
    };
  },
  defaultTheme: m => {
    m.extra.expoClient.extra.nativeApp = {
      ...config,
      themeKey: 'hypertodo.theme'
    };
  },
  wrongAccount: m => {
    m.extra.expoGo.username = 'anonymous';
  },
  wrongEntry: m => {
    m.extra.expoGo.mainModuleName = 'App';
  },
  wrongSDK: m => {
    m.extra.expoClient.sdkVersion = '56.0.0';
  },
  wrongPlatform: m => {
    m.launchAsset.url = m.launchAsset.url.replace('platform=ios', 'platform=android');
  },
  wrongSource: m => {
    m.extra.expoGo.developer.projectRoot = '/original';
  },
  unknownField: m => {
    m.extra.expoClient.extra.nativeApp = {
      ...config,
      token: 'secret'
    };
  }
})) test(`rejects ${name} rather than weakening the old guard`, () => {
  const m = manifest();
  modify(m);
  assert.throws(() => validateServedManifest(m, expected), /native-app-preflight/);
});
test('rejects service wildcard/public/reused alias and invalid expected provenance', () => {
  for (const change of [{
    apiOrigin: 'http://0.0.0.0:8787'
  }, {
    metroOrigin: apiOrigin
  }, {
    apiOrigin: `https://hvt-${run}.local:8787`
  }, {
    run: 'bad'
  }, {
    credentialKey: 'original'
  }, {
    metroOrigin: `http://hvtm-${run}.local:8081`
  }]) assert.throws(() => validateFixtureConfig({
    ...config,
    ...change
  }), /native-app-preflight/);
  assert.throws(() => validateServedManifest(manifest(), {
    ...expected,
    projectRoot: '/Users/original'
  }), /native-app-preflight/);
});
test('requires actual HTTP200 JavaScript/HMR/factory dependency graph', () => {
  for (const value of [{
    status: 500,
    contentType: 'application/javascript',
    source: js
  }, {
    status: 200,
    contentType: 'text/html',
    source: js
  }, {
    status: 200,
    contentType: 'application/javascript',
    source: js.replace('createSessionApp', 'DefaultApp')
  }, {
    status: 200,
    contentType: 'application/javascript',
    source: js.replace('expo/src/async-require/hmr.ts', '')
  }, {
    status: 200,
    contentType: 'application/javascript',
    source: js.replace('createSessionCredentialPort', '')
  }]) assert.throws(() => validateDevelopmentJavaScript(value, expected), /native-app-preflight/);
});
test('bounded development body reader rejects overflow and invalid UTF8', async () => {
  const {
    textBounded
  } = require('./check-development.cjs');
  assert.equal(await textBounded(new Response('actual source'), 100), 'actual source');
  await assert.rejects(textBounded(new Response('long'), 2), /oversize/);
  await assert.rejects(textBounded(new Response(new Uint8Array([255])), 2));
});
test('rejects unsafe independent expectations before any development HTTP', async () => {
  const {
    checkDevelopment
  } = require('./check-development.cjs');
  let calls = 0;
  await assert.rejects(checkDevelopment({
    ...expected,
    metroOrigin: 'http://public.invalid:8082'
  }, {
    http: async () => {
      calls++;
      return new Response('');
    },
    readEntry: () => require('./launcher.cjs').launcherFiles(expected, '/readonly/modules')['index.js']
  }));
  assert.equal(calls, 0);
});
