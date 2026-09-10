'use strict';
// Disposable Android System Proxy only; never a general forward proxy.
const http = require('node:http');
const net = require('node:net');
const WS_PATHS = new Set(['/hot', '/message', '/events']);
function configuration(input) {
  const integer = (v, min, max) => Number.isInteger(v) && v >= min && v <= max;
  const value = { port: 0, lifetimeMs: 600000, ...input };
  const valid = (route, kind) => {
    if (!route || Object.keys(route).some(k => !['authority', 'upstreamPort'].includes(k))) return false;
    const match = new RegExp(`^${kind}-([a-f0-9]{32})\\.local:([1-9][0-9]{0,4})$`).exec(route.authority);
    return match && integer(Number(match[2]), 1, 65535) && Number(match[2]) !== 8081 &&
      integer(route.upstreamPort, 1, 65535) && route.upstreamPort !== 8081 && match[1];
  };
  const a = valid(value.api, 'hvt'), m = valid(value.metro, 'hvtm');
  if (Object.keys(value).some(k => !['port', 'lifetimeMs', 'api', 'metro'].includes(k)) ||
      !integer(value.port, 0, 65535) || value.port === 8081 ||
      !integer(value.lifetimeMs, 1, 600000) || !a || a !== m) throw Error('invalid-system-proxy-config');
  return Object.freeze({ ...value, api: Object.freeze({ ...value.api }), metro: Object.freeze({ ...value.metro }) });
}
function target(req, config, upgrade) {
  const hosts = req.rawHeaders.filter((_, i) => i % 2 === 0 && req.rawHeaders[i].toLowerCase() === 'host');
  if (hosts.length !== 1 || req.headers['proxy-authorization'] !== undefined ||
      typeof req.url !== 'string' || req.url.length > 8192 || /[\\#\x00-\x20\x7f]/.test(req.url)) return null;
  const name = ['api', 'metro'].find(k => config[k].authority === req.headers.host);
  if (!name) return null;
  const route = config[name], prefix = `http://${route.authority}`;
  // Preserve the original encoded path/query, never normalize it through URL.
  let path = req.url;
  if (path.startsWith(prefix + '/')) path = path.slice(prefix.length);
  else if (!path.startsWith('/') || path.startsWith('//')) return null;
  if (req.headers.origin !== undefined && req.headers.origin !== prefix) return null;
  if (upgrade && (name !== 'metro' || req.method !== 'GET' || !WS_PATHS.has(path.split('?')[0]))) return null;
  return { name, route, path };
}
function rejectSocket(socket, status) {
  socket.end(`HTTP/1.1 ${status} ${http.STATUS_CODES[status]}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
}
function fail(res, status) {
  if (res.headersSent) res.destroy();
  else { res.writeHead(status, { Connection: 'close', 'Content-Length': 0 }); res.end(); }
}
async function startAndroidSystemProxy(input) {
  const config = configuration(input), sockets = new Set(), active = new Set();
  const counts = { api: 0, metro: 0 };
  let isClosed = false, closing, timer, finish, reservations = 0;
  const closed = new Promise(resolve => { finish = resolve; });
  const server = http.createServer({ maxHeaderSize: 16384 });
  server.headersTimeout = 10000; server.requestTimeout = 120000;
  server.keepAliveTimeout = 5000; server.maxRequestsPerSocket = 500;
  const track = socket => {
    if (isClosed) { socket.destroy(); return; }
    sockets.add(socket); socket.on('error', () => {});
    socket.setTimeout(120000, () => socket.destroy());
    socket.once('close', () => sockets.delete(socket));
  };
  server.on('connection', socket => {
    if (isClosed || sockets.size + reservations >= 64) { socket.destroy(); return; }
    track(socket);
  });
  server.on('clientError', (_error, socket) => rejectSocket(socket, 400));
  server.on('connect', (_req, socket) => rejectSocket(socket, 405));
  server.on('request', (req, res) => {
    const selected = target(req, config, false);
    if (!selected) { fail(res, 403); return; }
    if (isClosed || active.size >= 32 || sockets.size + reservations >= 64) { fail(res, 503); return; }
    if (Number(req.headers['content-length']) > 1048576) { fail(res, 413); return; }
    reservations++;
    let reserved = true;
    const release = () => { if (reserved) { reserved = false; reservations--; } };
    const outgoing = http.request({ hostname: '127.0.0.1', port: selected.route.upstreamPort,
      path: selected.path, method: req.method, headers: req.rawHeaders, agent: false, maxHeaderSize: 16384 });
    let response, bytes = 0, ended = false;
    const cancel = () => {
      if (ended) return; ended = true; release(); active.delete(cancel); clearTimeout(deadline);
      req.unpipe(outgoing); response?.unpipe(res); response?.destroy(); outgoing.destroy();
    };
    const deadline = setTimeout(() => { fail(res, 504); cancel(); }, 120000);
    active.add(cancel); counts[selected.name]++;
    outgoing.on('socket', socket => { release(); track(socket); });
    outgoing.on('error', () => { if (!ended) fail(res, 502); cancel(); });
    outgoing.on('response', incoming => {
      if (ended) { incoming.destroy(); return; } response = incoming;
      res.writeHead(incoming.statusCode, incoming.statusMessage, incoming.rawHeaders);
      incoming.on('error', () => { res.destroy(); cancel(); }); incoming.pipe(res);
    });
    req.on('data', chunk => { bytes += chunk.length; if (bytes > 1048576) { fail(res, 413); cancel(); } });
    req.on('aborted', cancel); res.on('close', cancel); req.pipe(outgoing);
  });
  server.on('upgrade', (req, socket, head) => {
    const selected = target(req, config, true);
    if (!selected) { rejectSocket(socket, 403); return; }
    if (isClosed || active.size >= 32 || sockets.size + reservations >= 64) { rejectSocket(socket, 503); return; }
    // Existing Metro proxy validates the actual handshake and owns /hot semantics.
    const remote = net.connect(selected.route.upstreamPort, '127.0.0.1'); track(remote);
    let ended = false;
    const cancel = () => {
      if (ended) return; ended = true; active.delete(cancel);
      socket.destroy(); remote.destroy();
    };
    active.add(cancel); counts.metro++;
    socket.once('close', cancel); remote.once('close', cancel);
    remote.once('error', () => { rejectSocket(socket, 502); cancel(); });
    remote.once('connect', () => {
      remote.write(`GET ${selected.path} HTTP/1.1\r\n` + req.rawHeaders.reduce((s, v, i) => s + v + (i % 2 ? '\r\n' : ': '), '') + '\r\n');
      if (head.length) remote.write(head); socket.pipe(remote); remote.pipe(socket);
    });
  });
  const close = () => {
    if (closing) return closing; isClosed = true; clearTimeout(timer);
    closing = new Promise(resolve => {
      for (const cancel of [...active]) cancel(); for (const socket of sockets) socket.destroy();
      server.close(() => { sockets.clear(); finish(); resolve(); });
    }); return closing;
  };
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(config.port, '127.0.0.1', resolve); });
  timer = setTimeout(close, config.lifetimeMs);
  return Object.freeze({ address: Object.freeze({ ...server.address() }), close, closed,
    snapshot: () => Object.freeze({ closed: isClosed, connections: sockets.size, inFlight: active.size, ...counts }) });
}
module.exports = { startAndroidSystemProxy };
