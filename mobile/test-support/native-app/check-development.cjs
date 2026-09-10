'use strict';

// Explicit HTTP-only coordinator acceptance. Does not launch Metro or a client.
const fs = require('node:fs');
const {roots}=require('../portable-paths.cjs');
const {
  validateServedManifest,
  validateDevelopmentJavaScript,
  validateExpectations
} = require('./preflight.cjs');
const {
  validateEntry
} = require('./launcher.cjs');
async function textBounded(response, max) {
  if (!response.body) throw new Error('missing-body');
  const reader = response.body.getReader(),
    chunks = [];
  let size = 0;
  try {
    for (;;) {
      const {
        value,
        done
      } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > max) throw new Error('oversize');
      chunks.push(value);
    }
  } finally {
    await reader.cancel();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  return new TextDecoder('utf-8', {
    fatal: true
  }).decode(bytes);
}
async function checkDevelopment(expected, {
  http = fetch,
  readEntry = () => fs.readFileSync(expected.projectRoot + '/index.js', 'utf8')
} = {}) {
  validateExpectations(expected);
  validateEntry(readEntry(),roots(expected).sourceRoot);
  const manifestResponse = await http(expected.metroOrigin, {
    headers: {
      'expo-platform': expected.platform,
      Accept: 'application/expo+json,application/json'
    },
    redirect: 'error',
    signal: AbortSignal.timeout(15000)
  });
  if (manifestResponse.status !== 200) throw new Error('manifest-status');
  const manifest = JSON.parse(await textBounded(manifestResponse, 1024 * 1024));
  validateServedManifest(manifest, expected);
  const response = await http(manifest.launchAsset.url, {
    redirect: 'error',
    signal: AbortSignal.timeout(120000)
  });
  validateDevelopmentJavaScript({
    status: response.status,
    contentType: response.headers.get('content-type'),
    source: await textBounded(response, 32 * 1024 * 1024)
  }, expected);
  return Object.freeze({
    manifest: true,
    developmentJavaScript: true,
    entry: true,
    native: 'NOT_RUN'
  });
}
async function main() {
  if (process.argv.length !== 3 || fs.statSync(process.argv[2]).size > 4096) throw new Error('expectations');
  const expected = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  process.stdout.write(JSON.stringify(await checkDevelopment(expected)) + '\n');
}
if (require.main === module) void main().catch(() => {
  process.stderr.write('native-app-development: check failed\n');
  process.exitCode = 1;
});
module.exports = {
  textBounded,
  checkDevelopment
};
