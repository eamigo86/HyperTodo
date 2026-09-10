'use strict';

// Test-only: keep the authenticated Expo server on loopback, without replacing it.
const http = require('node:http');
const net = require('node:net');
const { createHash } = require('node:crypto');
const ENDPOINTS = new Set(['/hot', '/message', '/events']);
const GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';

/** Validate explicit addresses and finite bounds before creating any socket. */
function configuration(input) {
  const value = {
    lifetimeMs: 600000, idleTimeoutMs: 120000, requestTimeoutMs: 120000,
    maxConnections: 32, maxInFlight: 32, maxRequestBytes: 1048576,
    ...input,
  };
  const integer = (x, min, max) => Number.isInteger(x) && x >= min && x <= max;
  const privateAddress = address => {
    if (net.isIP(address) !== 4) return false;
    const [a, b] = address.split('.').map(Number);
    return a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || address === '127.0.0.1';
  };
  if (!privateAddress(value.bindAddress) ||
      !/^hvtm-[a-f0-9]{32}\.local$/.test(value.hostname) ||
      !['127.0.0.1', '::1'].includes(value.upstreamAddress) ||
      !integer(value.port, 0, 65535) || !integer(value.upstreamPort, 1, 65535) ||
      value.port === 8081 || value.upstreamPort === 8081 || value.port === value.upstreamPort ||
      !integer(value.lifetimeMs, 1, 600000) || !integer(value.idleTimeoutMs, 1, 120000) ||
      !integer(value.requestTimeoutMs, 1, 120000) ||
      !integer(value.maxConnections, 1, 32) || !integer(value.maxInFlight, 1, 32) ||
      !integer(value.maxRequestBytes, 1, 1048576)) throw new Error('invalid-proxy-config');
  return Object.freeze(value);
}

/** Return a generic status for invalid requests; never select an upstream from input. */
function rejection(req, authority, upgrade = false) {
  let hostCount = 0;
  for (let index = 0; index < req.rawHeaders.length; index += 2) {
    if (req.rawHeaders[index].toLowerCase() === 'host') hostCount++;
  }
  if (hostCount !== 1 || req.headers.host !== authority ||
      (req.headers.origin !== undefined && req.headers.origin !== `http://${authority}`)) return 403;
  if (typeof req.url !== 'string' || req.url.length > 8192 || !req.url.startsWith('/') ||
      req.url.startsWith('//') || /[\\#\x00-\x20\x7f]/.test(req.url)) return 400;
  if (req.method === 'CONNECT') return 405;
  if (upgrade) {
    const key = req.headers['sec-websocket-key'];
    if (req.method !== 'GET' || req.httpVersion !== '1.1' ||
        !ENDPOINTS.has(req.url.split('?')[0]) ||
        req.headers.upgrade?.toLowerCase() !== 'websocket' ||
        !req.headers.connection?.toLowerCase().split(/\s*,\s*/).includes('upgrade') ||
        req.headers['sec-websocket-version'] !== '13' ||
        typeof key !== 'string' || !/^[A-Za-z0-9+/]{22}==$/.test(key) ||
        Buffer.from(key, 'base64').length !== 16) return 400;
  }
  return null;
}

/** Emit fixed text only; credentials and upstream errors never enter logs or errors. */
function fail(response, status, text) {
  if (response.headersSent) { response.destroy(); return; }
  response.writeHead(status, { 'Content-Type': 'text/plain', 'Content-Length': Buffer.byteLength(text), Connection: 'close' });
  response.end(text);
}

/** Write an HTTP rejection on a raw upgrade/CONNECT socket. */
function rejectSocket(socket, status) {
  socket.end(`HTTP/1.1 ${status} ${http.STATUS_CODES[status]}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
}

/** Start a bounded owned proxy. The caller must close it; lifetime is a hard fallback. */
async function startMetroProxy(input) {
  const config = configuration(input);
  const incoming = new Set(), upstreamSockets = new Set(), active = new Set();
  let isClosed = false, closePromise, expire, authority;
  let finishClosed;
  const closed = new Promise(resolve => { finishClosed = resolve; });
  const server = http.createServer({ maxHeaderSize: 16384 });
  server.headersTimeout = Math.min(config.requestTimeoutMs, 10000);
  server.requestTimeout = config.requestTimeoutMs;
  server.keepAliveTimeout = 5000;
  server.maxRequestsPerSocket = 500;

  /** Track exclusively sockets created by this proxy, including upgraded ones. */
  const trackUpstream = socket => {
    upstreamSockets.add(socket);
    socket.once('close', () => upstreamSockets.delete(socket));
    socket.on('error', () => {});
  };
  /** Idempotently close every owned transport; no external server is touched. */
  const close = () => {
    if (closePromise) return closePromise;
    isClosed = true;
    clearTimeout(expire);
    closePromise = new Promise(resolve => {
      for (const cancel of [...active]) cancel();
      for (const socket of incoming) socket.destroy();
      for (const socket of upstreamSockets) socket.destroy();
      server.close(() => {
        incoming.clear(); upstreamSockets.clear(); active.clear();
        finishClosed(); resolve();
      });
    });
    return closePromise;
  };
  server.on('connection', socket => {
    socket.on('error', () => {});
    if (isClosed || incoming.size >= config.maxConnections) { socket.destroy(); return; }
    incoming.add(socket);
    socket.setTimeout(config.idleTimeoutMs, () => socket.destroy());
    socket.once('close', () => incoming.delete(socket));
  });
  server.on('clientError', (_error, socket) => rejectSocket(socket, 400));
  server.on('connect', (_req, socket) => rejectSocket(socket, 405));

  server.on('request', (req, res) => {
    const status = rejection(req, authority);
    if (status) { fail(res, status, 'proxy-request-rejected'); return; }
    if (isClosed || active.size >= config.maxInFlight) { fail(res, 503, 'proxy-capacity'); return; }
    const declaredLength = req.headers['content-length'];
    if (declaredLength && Number(declaredLength) > config.maxRequestBytes) { fail(res, 413, 'proxy-body-limit'); return; }
    let upstreamResponse, timer, completed = false;
    const upstream = http.request({
      hostname: config.upstreamAddress, port: config.upstreamPort,
      path: req.url, method: req.method, headers: req.rawHeaders,
      agent: false, maxHeaderSize: 16384,
    });
    const cancel = () => {
      if (completed) return;
      completed = true;
      clearTimeout(timer); active.delete(cancel);
      req.unpipe(upstream);
      upstreamResponse?.unpipe(res);
      upstreamResponse?.destroy(); upstream.destroy();
    };
    active.add(cancel);
    timer = setTimeout(() => { fail(res, 504, 'proxy-request-timeout'); cancel(); }, config.requestTimeoutMs);
    upstream.on('socket', trackUpstream);
    upstream.on('error', () => { if (!completed) fail(res, 502, 'proxy-upstream-error'); cancel(); });
    upstream.on('response', response => {
      if (completed) { response.destroy(); return; }
      upstreamResponse = response;
      res.writeHead(response.statusCode, response.statusMessage, response.rawHeaders);
      response.on('error', () => { res.destroy(); cancel(); });
      response.pipe(res);
    });
    let size = 0;
    req.on('data', chunk => {
      size += chunk.length;
      if (size > config.maxRequestBytes) { fail(res, 413, 'proxy-body-limit'); cancel(); }
    });
    req.on('aborted', cancel);
    res.on('close', cancel);
    req.pipe(upstream);
  });

  server.on('upgrade', (req, socket, head) => {
    const status = rejection(req, authority, true);
    if (status) { rejectSocket(socket, status); return; }
    if (isClosed || active.size >= config.maxInFlight) { rejectSocket(socket, 503); return; }
    let upgraded, timer, completed = false;
    const upstream = http.request({
      hostname: config.upstreamAddress, port: config.upstreamPort,
      path: req.url, method: 'GET', headers: req.rawHeaders,
      agent: false, maxHeaderSize: 16384,
    });
    const cancel = () => {
      if (completed) return;
      completed = true;
      clearTimeout(timer); active.delete(cancel);
      socket.unpipe(upgraded); upgraded?.unpipe(socket);
      upstream.destroy(); upgraded?.destroy(); socket.destroy();
    };
    active.add(cancel);
    timer = setTimeout(() => { rejectSocket(socket, 504); upstream.destroy(); }, Math.min(config.requestTimeoutMs, 10000));
    socket.once('close', cancel);
    socket.once('end', cancel);
    upstream.on('socket', trackUpstream);
    upstream.on('error', () => { if (!completed) rejectSocket(socket, 502); });
    upstream.on('response', response => {
      // Keep real HTTP handshake refusals, without exposing any private diagnostics.
      upgraded = response.socket;
      response.on('error', cancel);
      // IncomingMessage has decoded chunk framing; let ServerResponse encode it.
      const refused = new http.ServerResponse(req);
      refused.assignSocket(socket);
      refused.writeHead(response.statusCode, response.statusMessage, response.rawHeaders);
      refused.once('finish', () => { clearTimeout(timer); socket.end(); });
      response.pipe(refused);
    });
    upstream.on('upgrade', (response, remote, remoteHead) => {
      if (completed) { remote.destroy(); return; }
      clearTimeout(timer);
      upgraded = remote;
      const expected = createHash('sha1').update(req.headers['sec-websocket-key'] + GUID).digest('base64');
      if (response.headers.upgrade?.toLowerCase() !== 'websocket' || response.headers['sec-websocket-accept'] !== expected) {
        rejectSocket(socket, 502); remote.destroy(); return;
      }
      remote.on('error', cancel);
      remote.once('close', cancel);
      remote.once('end', cancel);
      remote.setTimeout(config.idleTimeoutMs, cancel);
      socket.write(`HTTP/1.1 101 ${response.statusMessage}\r\n` + response.rawHeaders.reduce((text, item, index) => text + item + (index % 2 ? '\r\n' : ': '), '') + '\r\n');
      if (remoteHead.length) socket.write(remoteHead);
      if (head.length) remote.write(head);
      socket.pipe(remote); remote.pipe(socket);
    });
    upstream.end();
  });
  await new Promise((resolve, reject) => {
    server.once('error', () => { reject(new Error('proxy-listen-failed')); });
    server.listen(config.port, config.bindAddress, resolve);
  });
  const address = Object.freeze({ ...server.address() });
  authority = `${config.hostname}:${address.port}`;
  expire = setTimeout(close, config.lifetimeMs);
  return Object.freeze({ address, close, closed, snapshot: () => Object.freeze({ closed: isClosed, connections: incoming.size, upstreams: upstreamSockets.size, inFlight: active.size }) });
}

module.exports = { startMetroProxy };

if (require.main === module) {
  // Explicit positional arguments avoid environment-dependent wildcard defaults.
  const [bindAddress, port, hostname, upstreamAddress, upstreamPort, ...rest] = process.argv.slice(2);
  if (rest.length || !port || !upstreamPort || Number(port) === 0 || bindAddress === '127.0.0.1') {
    process.stderr.write('invalid-proxy-config\n'); process.exitCode = 1;
  } else {
    startMetroProxy({ bindAddress, port: Number(port), hostname, upstreamAddress, upstreamPort: Number(upstreamPort) }).then(instance => {
      const stop = () => instance.close();
      process.once('SIGINT', stop); process.once('SIGTERM', stop);
      process.stdout.write(JSON.stringify({ event: 'proxy-ready', address: instance.address.address, port: instance.address.port, lifetimeMs: 600000 }) + '\n');
      instance.closed.then(() => {
        process.removeListener('SIGINT', stop); process.removeListener('SIGTERM', stop);
        process.stdout.write('{"event":"proxy-closed"}\n');
      });
    }, () => { process.stderr.write('proxy-start-failed\n'); process.exitCode = 1; });
  }
}
