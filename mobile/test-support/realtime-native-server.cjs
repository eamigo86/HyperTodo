'use strict';

// Test-only native I/O prerequisite. Never mount this in application routing.
const { randomBytes, timingSafeEqual } = require('node:crypto');
const { createServer } = require('node:http');
const { isIP } = require('node:net');

const CHECKS = ['bootstrapOk', 'firstFrameRead', 'secondFrameRead', 'abortRequested', 'serverCloseObserved'];
const STAGES = ['metadata', 'bootstrap', 'stream', 'first-frame', 'first-ack', 'second-frame', 'second-ack', 'abort', 'report'];
const ERRORS = ['unsupported-runtime', 'request-failed', 'timeout', 'unexpected-status', 'invalid-stream', 'invalid-frame', 'server-not-closed', 'cancelled', 'report-upload-failed'];
const CLIENT_FIELDS = ['platform', 'clientVersion', 'expoVersion', 'executionEnvironment', 'reactNativeVersion', 'checks', 'failedStage', 'errorCode'];

/** Return whether an object has exactly the allowlisted own properties. */
function exactKeys(value, keys) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === keys.length
    && keys.every((key) => Object.hasOwn(value, key));
}

/** Validate synthetic, bounded metadata without retaining arbitrary client text. */
function validClientReport(value) {
  return exactKeys(value, CLIENT_FIELDS)
    && ['ios', 'android'].includes(value.platform)
    && ['clientVersion', 'expoVersion', 'reactNativeVersion'].every((key) =>
      typeof value[key] === 'string' && /^[A-Za-z0-9][A-Za-z0-9._+-]{0,31}$/.test(value[key]))
    && ['storeClient', 'bare', 'standalone', 'unknown'].includes(value.executionEnvironment)
    && exactKeys(value.checks, CHECKS)
    && CHECKS.every((key) => typeof value.checks[key] === 'boolean')
    && (value.failedStage === null || STAGES.includes(value.failedStage))
    && (value.errorCode === null || ERRORS.includes(value.errorCode));
}

/** Create a one-shot memory-only fixture; listening is a separate explicit action. */
function createProbeServer({
  host = '127.0.0.1', port = 0, streamDeadlineMs = 30000,
  lifetimeMs = 300000, onEvidence = () => {},
} = {}) {
  if (isIP(host) !== 4 || !Number.isInteger(port) || port < 0 || port > 65535
      || !Number.isInteger(streamDeadlineMs) || streamDeadlineMs < 1 || streamDeadlineMs > 60000
      || !Number.isInteger(lifetimeMs) || lifetimeMs < 1 || lifetimeMs > 600000
      || typeof onEvidence !== 'function') {
    throw new TypeError('invalid probe configuration');
  }
  const suffix = randomBytes(16).toString('hex');
  const runPath = `/probe-${suffix}`;
  const cookieName = `djhv_probe_${suffix}`;
  const cookieValue = randomBytes(24).toString('hex');
  const cookieOptions = `Path=${runPath}/; HttpOnly; SameSite=Strict`;
  const tokens = [randomBytes(24).toString('hex'), randomBytes(24).toString('hex')];
  const state = {
    bootstrapCount: 0, streamAuthorized: false, firstFrameSent: false,
    firstAckReceived: false, secondFrameSent: false, secondAckReceived: false,
    streamClosed: false, closeReason: null, activeStreams: 0,
  };
  let client = null;
  let stream = null;
  let streamTimer = null;
  let lifetimeTimer = null;
  let closePromise = null;
  let origin = null;
  let requestCount = 0;

  /** Return server observations only, never a verdict about the native SDK. */
  function report() {
    return {
      ...state,
      passed: state.streamAuthorized && state.firstAckReceived && state.secondAckReceived
        && state.streamClosed && state.closeReason === 'client',
    };
  }

  /** Emit only constructed metadata; a failing evidence sink must not leak errors. */
  function evidence(kind) {
    try { onEvidence({ kind, server: report(), client: client && structuredClone(client) }); }
    catch { /* Evidence destination failure cannot inject a secret-bearing traceback. */ }
  }

  /** Check only the unique fixture cookie; unrelated cookies are never stored. */
  function authorized(req) {
    const values = (req.headers.cookie || '').split(';').map((entry) => entry.trim())
      .filter((entry) => entry.startsWith(`${cookieName}=`));
    if (values.length !== 1) return false;
    const supplied = Buffer.from(values[0].slice(cookieName.length + 1));
    const expected = Buffer.from(cookieValue);
    return supplied.length === expected.length && timingSafeEqual(supplied, expected);
  }

  /** Return a small uncacheable response, closing connections carrying rejected input. */
  function reply(res, status, value, headers = {}) {
    res.writeHead(status, {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store, no-transform',
      ...(status >= 400 ? { Connection: 'close' } : {}), ...headers,
    });
    res.end(status === 204 ? undefined : JSON.stringify(value));
  }

  /** Read bounded JSON with a deadline; Content-Length is never the sole bound. */
  function readJson(req, res, maximum, accept) {
    if ((req.headers['content-type'] || '').split(';')[0].trim() !== 'application/json') {
      reply(res, 415, { error: 'unsupported-media-type' }); return;
    }
    let finished = false;
    let size = 0;
    const chunks = [];
    const timer = setTimeout(() => finish(408, 'request-timeout'), 2000);
    timer.unref();
    function finish(status, code) {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      if (status && !res.destroyed) reply(res, status, { error: code });
    }
    req.on('error', () => finish());
    req.on('aborted', () => finish());
    req.on('data', (chunk) => {
      if (finished) return;
      size += chunk.length;
      if (size > maximum) { finish(413, 'body-too-large'); return; }
      chunks.push(chunk);
    });
    req.on('end', () => {
      if (finished) return;
      finish();
      let value;
      try { value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks))); }
      catch { reply(res, 400, { error: 'invalid-body' }); return; }
      accept(value);
    });
    const length = req.headers['content-length'];
    if (length && Number(length) > maximum) finish(413, 'body-too-large');
  }

  /** Deliberately split each frame; the next frame waits for its predecessor's token. */
  function sendFrame(stage) {
    if (!stream || stream.destroyed) return;
    const target = stream;
    target.write('event: probe\ndata: ');
    setImmediate(() => {
      if (target.destroyed || target !== stream) return;
      target.write(`${JSON.stringify({ stage, token: tokens[stage - 1] })}\n\n`);
      state[stage === 1 ? 'firstFrameSent' : 'secondFrameSent'] = true;
      evidence(stage === 1 ? 'first-frame' : 'second-frame');
    });
  }

  /** End all fixture resources without misclassifying cleanup as a client abort. */
  function close() {
    if (closePromise) return closePromise;
    clearTimeout(lifetimeTimer);
    clearTimeout(streamTimer);
    if (stream && !stream.destroyed) {
      state.closeReason = 'shutdown';
      stream.destroy();
    }
    closePromise = new Promise((resolve) => {
      server.close(resolve);
      server.closeAllConnections();
    });
    return closePromise;
  }

  const methods = { bootstrap: 'GET', stream: 'GET', ack: 'POST', report: 'GET', 'client-report': 'POST', reset: 'POST' };
  const server = createServer({ maxHeaderSize: 8192 }, (req, res) => {
    requestCount += 1;
    if (requestCount > 128) { reply(res, 429, { error: 'request-limit' }); return; }
    const route = Object.keys(methods).find((name) => req.url === `${runPath}/${name}`);
    if (!route) { reply(res, 404, { error: 'not-found' }); return; }
    if (req.headers.origin && req.headers.origin !== origin) {
      reply(res, 403, { error: 'forbidden' }); return;
    }
    if (req.method !== methods[route]) {
      reply(res, 405, { error: 'method-not-allowed' }, { Allow: methods[route] }); return;
    }
    if (route === 'bootstrap') {
      state.bootstrapCount += 1;
      reply(res, 200, { ok: true }, { 'Set-Cookie': `${cookieName}=${cookieValue}; ${cookieOptions}; Max-Age=120` });
      evidence('bootstrap'); return;
    }
    if (!authorized(req)) { reply(res, 403, { error: 'forbidden' }); return; }
    if (route === 'report') {
      reply(res, 200, { server: report(), client }); return;
    }
    if (route === 'reset') {
      reply(res, 204, null, { 'Set-Cookie': `${cookieName}=; ${cookieOptions}; Max-Age=0` }); return;
    }
    if (route === 'client-report') {
      readJson(req, res, 2048, (value) => {
        if (!validClientReport(value)) { reply(res, 400, { error: 'invalid-body' }); return; }
        client = value;
        reply(res, 204);
        evidence('client-report');
      });
      return;
    }
    if (route === 'ack') {
      readJson(req, res, 256, (value) => {
        if (!exactKeys(value, ['token']) || typeof value.token !== 'string'
            || value.token.length < 1 || value.token.length > 96) {
          reply(res, 400, { error: 'invalid-body' }); return;
        }
        if (!stream || stream.destroyed) { reply(res, 409, { error: 'no-active-stream' }); return; }
        if (!state.firstAckReceived && state.firstFrameSent && value.token === tokens[0]) {
          state.firstAckReceived = true;
          reply(res, 204);
          sendFrame(2);
          return;
        }
        if (state.firstAckReceived && state.secondFrameSent && !state.secondAckReceived && value.token === tokens[1]) {
          state.secondAckReceived = true;
          reply(res, 204);
          evidence('second-ack'); return;
        }
        reply(res, 403, { error: 'forbidden' });
      });
      return;
    }
    if (state.streamAuthorized) { reply(res, 409, { error: 'stream-already-used' }); return; }
    state.streamAuthorized = true;
    state.activeStreams = 1;
    stream = res;
    res.on('close', () => {
      clearTimeout(streamTimer);
      state.activeStreams = 0;
      state.streamClosed = true;
      state.closeReason ||= 'client';
      evidence('stream-close');
    });
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-store, no-transform', 'X-Accel-Buffering': 'no',
    });
    res.flushHeaders();
    res.socket.setNoDelay(true);
    streamTimer = setTimeout(() => {
      state.closeReason = 'deadline';
      res.destroy();
    }, streamDeadlineMs);
    streamTimer.unref();
    sendFrame(1);
  });
  server.maxConnections = 8;
  server.maxRequestsPerSocket = 16;
  server.headersTimeout = 5000;
  server.requestTimeout = 5000;
  server.keepAliveTimeout = 1000;

  return {
    report, close,
    async listen() {
      await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(port, host, () => { server.removeListener('error', reject); resolve(); });
      });
      origin = `http://${host}:${server.address().port}`;
      lifetimeTimer = setTimeout(() => { void close(); }, lifetimeMs);
      lifetimeTimer.unref();
      return { baseUrl: `${origin}${runPath}`, runPath };
    },
  };
}

/** CLI keeps stdout limited to the run capability and sanitized observations. */
async function main() {
  const args = process.argv.slice(2);
  if (args.length === 1 && args[0] === '--help') {
    process.stdout.write('test-only native I/O probe: node realtime-native-server.cjs [--host IPv4] [--port 0..65535]\nDefault: 127.0.0.1, ephemeral port; LAN requires separate authorization.\n');
    return;
  }
  const options = {};
  for (let index = 0; index < args.length; index += 2) {
    if (!['--host', '--port'].includes(args[index]) || !args[index + 1]) throw new Error('invalid arguments');
    options[args[index].slice(2)] = args[index] === '--port' ? Number(args[index + 1]) : args[index + 1];
  }
  const probe = createProbeServer({ ...options, onEvidence: (event) => process.stdout.write(`${JSON.stringify(event)}\n`) });
  const address = await probe.listen();
  process.stdout.write(`${JSON.stringify({ kind: 'ready', ...address })}\n`);
  for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => { void probe.close(); });
}

module.exports = { createProbeServer };
if (require.main === module) main().catch(() => {
  process.stderr.write('probe startup failed\n');
  process.exitCode = 1;
});
