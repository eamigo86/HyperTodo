'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const net = require('node:net');
const { once } = require('node:events');
const { createHash } = require('node:crypto');
const { startMetroProxy } = require('./metro-proxy.cjs');

const hostname = `hvtm-${'a'.repeat(32)}.local`;
const options = { bindAddress: '127.0.0.1', port: 0, hostname, upstreamAddress: '127.0.0.1', upstreamPort: 12345, lifetimeMs: 10000 };
const key = 'dGhlIHNhbXBsZSBub25jZQ==';
const accept = createHash('sha1').update(`${key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`).digest('base64');
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; }
async function upstream(t, handler) {
  const server = http.createServer(handler);
  const sockets = new Set();
  server.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)); });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  t.after(async () => { for (const socket of sockets) socket.destroy(); await new Promise(resolve => server.close(resolve)); });
  return server;
}
async function proxy(t, server, extra = {}) {
  const instance = await startMetroProxy({ ...options, upstreamPort: server.address().port, ...extra });
  t.after(() => instance.close());
  return instance;
}
function request(instance, { path = '/index.bundle?platform=ios&dev=true', method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port: instance.address.port, method, path, headers: { Host: `${hostname}:${instance.address.port}`, ...headers } }, res => {
      const chunks = [];
      res.on('data', b => chunks.push(b));
      res.on('error', reject);
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
    });
    req.on('error', reject);
    req.end(body);
  });
}
async function raw(instance, text) {
  const socket = net.connect(instance.address.port, '127.0.0.1');
  const chunks = [];
  socket.on('data', value => chunks.push(value));
  socket.on('error', () => {});
  const closed = once(socket, 'close');
  socket.write(text);
  await closed;
  return Buffer.concat(chunks).toString('latin1');
}
function upgradeText(instance, path = '/hot?platform=ios', extra = '') {
  return `GET ${path} HTTP/1.1\r\nHost: ${hostname}:${instance.address.port}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: ${key}\r\n${extra}\r\n`;
}

test('requires explicit bounded private/loopback addresses, fresh hostname and separate ports', async () => {
  for (const extra of [
    { bindAddress: undefined }, { bindAddress: '0.0.0.0' }, { bindAddress: '::' }, { bindAddress: '8.8.8.8' },
    { bindAddress: 'localhost' }, { hostname: 'localhost' }, { hostname: '*.local' }, { hostname: `${hostname}:80` },
    { upstreamAddress: '192.168.4.43' }, { upstreamAddress: 'localhost' }, { upstreamPort: 0 },
    { port: 8081 }, { upstreamPort: 8081 }, { port: 12345 }, { lifetimeMs: 600001 }, { lifetimeMs: 0 },
    { maxConnections: 33 }, { maxInFlight: 33 }, { requestTimeoutMs: 120001 }, { idleTimeoutMs: 120001 },
  ]) await assert.rejects(startMetroProxy({ ...options, ...extra }), { message: 'invalid-proxy-config' });
});

test('binds the exact address and forwards HTTP status, duplicate headers, credentials and streamed bytes', { timeout: 5000 }, async t => {
  const seen = deferred();
  const server = await upstream(t, (req, res) => {
    const chunks = [];
    req.on('data', b => chunks.push(b));
    req.on('end', () => {
      seen.resolve({ url: req.url, method: req.method, headers: req.headers, body: Buffer.concat(chunks) });
      res.writeHead(206, { 'Content-Type': 'application/javascript', 'Set-Cookie': ['own-a=1', 'own-b=2'], 'Expo-Protocol-Version': '1' });
      res.write(Buffer.from([0, 255, 10])); res.end('tail');
    });
  });
  const instance = await proxy(t, server);
  assert.equal(instance.address.address, '127.0.0.1');
  const response = await request(instance, { method: 'POST', body: 'unchanged csrf=a&x=1&x=2', headers: { Cookie: 'synthetic=only', Authorization: 'synthetic-only', 'Expo-Platform': 'ios' } });
  assert.equal(response.status, 206);
  assert.deepEqual(response.headers['set-cookie'], ['own-a=1', 'own-b=2']);
  assert.equal(response.headers['expo-protocol-version'], '1');
  assert.deepEqual(response.body, Buffer.concat([Buffer.from([0, 255, 10]), Buffer.from('tail')]));
  const actual = await seen.promise;
  assert.equal(actual.url, '/index.bundle?platform=ios&dev=true');
  assert.equal(actual.method, 'POST');
  assert.equal(actual.headers.host, `${hostname}:${instance.address.port}`);
  assert.equal(actual.headers.cookie, 'synthetic=only');
  assert.equal(actual.headers.authorization, 'synthetic-only');
  assert.equal(actual.body.toString(), 'unchanged csrf=a&x=1&x=2');
});

test('rejects Host/origin confusion, absolute form, CONNECT and unsupported upgrades before upstream I/O', { timeout: 5000 }, async t => {
  let calls = 0;
  const server = await upstream(t, (_req, res) => { calls++; res.end(); });
  server.on('upgrade', (_req, socket) => { calls++; socket.destroy(); });
  const instance = await proxy(t, server);
  for (const headers of [{ Host: 'other.local' }, { Origin: 'http://evil.invalid' }]) assert.equal((await request(instance, { headers })).status, 403);
  for (const path of ['http://evil.invalid/proxy', '//evil.invalid/proxy', '/bad\\path']) assert.equal((await request(instance, { path })).status, 400);
  assert.match(await raw(instance, `CONNECT evil.invalid:443 HTTP/1.1\r\nHost: ${hostname}:${instance.address.port}\r\n\r\n`), /^HTTP\/1.1 405 /);
  assert.match(await raw(instance, upgradeText(instance, '/unknown')), /^HTTP\/1.1 400 /);
  assert.match(await raw(instance, upgradeText(instance).replace('Upgrade: websocket', 'Upgrade: other')), /^HTTP\/1.1 400 /);
  assert.match(await raw(instance, upgradeText(instance, '/hot', 'Origin: http://evil.invalid\r\n')), /^HTTP\/1.1 403 /);
  assert.match(await raw(instance, `GET / HTTP/1.1\r\nHost: ${hostname}:${instance.address.port}\r\nHost: evil.invalid\r\n\r\n`), /^HTTP\/1.1 403 /);
  assert.equal(calls, 0);
});

test('forwards websocket handshake and bytes bidirectionally including both upgrade head buffers', { timeout: 5000 }, async t => {
  const clientFrame = Buffer.from([0x81, 0x81, 1, 2, 3, 4, 0x79]); // masked x
  const serverFrame = Buffer.from([0x81, 1, 0x79]);
  const received = deferred(), closed = deferred(), afterUpgrade = deferred();
  const secondFrame = Buffer.from([0x81, 0x81, 4, 3, 2, 1, 0x7d]); // masked y
  const secondReply = Buffer.from([0x81, 1, 0x79]);
  const server = await upstream(t, (_req, res) => res.end());
  server.on('upgrade', (req, socket, head) => {
    assert.equal(req.url, '/hot?platform=ios');
    assert.equal(req.headers['sec-websocket-key'], key);
    const chunks = [head];
    socket.on('data', b => {
      chunks.push(b); received.resolve(Buffer.concat(chunks));
      if (Buffer.concat(chunks).length === clientFrame.length + secondFrame.length) {
        afterUpgrade.resolve(Buffer.concat(chunks).subarray(clientFrame.length));
        socket.write(secondReply);
      }
    });
    if (head.length) received.resolve(head);
    socket.on('end', () => socket.end());
    socket.on('close', closed.resolve);
    socket.write(Buffer.concat([Buffer.from(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`), serverFrame]));
  });
  const instance = await proxy(t, server);
  const socket = net.connect(instance.address.port, '127.0.0.1');
  t.after(() => socket.destroy());
  const data = deferred(), chunks = [];
  socket.on('data', b => { chunks.push(b); if (Buffer.concat(chunks).includes(serverFrame)) data.resolve(Buffer.concat(chunks)); });
  socket.write(Buffer.concat([Buffer.from(upgradeText(instance)), clientFrame]));
  assert.deepEqual(await received.promise, clientFrame);
  const reply = await data.promise;
  assert.match(reply.toString('latin1'), /^HTTP\/1.1 101 Switching Protocols/);
  assert.deepEqual(reply.subarray(reply.indexOf('\r\n\r\n') + 4), serverFrame);
  const nextData = once(socket, 'data');
  socket.write(secondFrame);
  assert.deepEqual(await afterUpgrade.promise, secondFrame);
  assert.deepEqual((await nextData)[0], secondReply);
  socket.destroy();
  await closed.promise;
});

test('allows only the installed native HMR/messages/events websocket endpoints', { timeout: 5000 }, async t => {
  const server = await upstream(t, (_req, res) => res.end());
  const paths = [];
  server.on('upgrade', (req, socket) => { paths.push(req.url); socket.end('HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'); });
  const instance = await proxy(t, server);
  for (const path of ['/hot', '/message', '/events']) assert.match(await raw(instance, upgradeText(instance, path)), /^HTTP\/1.1 403 /);
  assert.deepEqual(paths, ['/hot', '/message', '/events']);
});

test('streams the first HTTP chunk before upstream completes (no full bundle buffering)', { timeout: 5000 }, async t => {
  let finish;
  const server = await upstream(t, (_req, res) => { res.write('first'); finish = () => res.end('last'); });
  const instance = await proxy(t, server);
  await new Promise((resolve, reject) => {
    const req = http.get({ host: '127.0.0.1', port: instance.address.port, headers: { Host: `${hostname}:${instance.address.port}` } }, res => {
      const chunks = [];
      res.once('data', b => { assert.equal(b.toString(), 'first'); finish(); });
      res.on('data', b => chunks.push(b));
      res.on('end', () => { assert.equal(Buffer.concat(chunks).toString(), 'firstlast'); resolve(); });
    });
    req.on('error', reject);
  });
});

test('client cancellation closes its upstream, and explicit close destroys only owned sockets', { timeout: 5000 }, async t => {
  const started = deferred(), stopped = deferred();
  const server = await upstream(t, (_req, res) => { res.write('pending'); res.on('close', stopped.resolve); started.resolve(); });
  const instance = await proxy(t, server);
  const req = http.get({ host: '127.0.0.1', port: instance.address.port, headers: { Host: `${hostname}:${instance.address.port}` } });
  req.on('error', () => {});
  await started.promise;
  req.destroy();
  await stopped.promise;
  const idle = net.connect(instance.address.port, '127.0.0.1');
  await once(idle, 'connect');
  idle.on('error', () => {});
  const closed = new Promise(resolve => idle.once('close', resolve));
  await instance.close(); await closed;
  assert.deepEqual(instance.snapshot(), { closed: true, connections: 0, upstreams: 0, inFlight: 0 });
  assert.equal(server.listening, true);
});

test('closes upgraded owned sockets at the finite lifetime and releases listener', { timeout: 5000 }, async t => {
  const server = await upstream(t, (_req, res) => res.end());
  const upgraded = deferred(), remoteClosed = deferred();
  server.on('upgrade', (_req, socket) => {
    socket.on('end', () => socket.end());
    socket.on('close', remoteClosed.resolve);
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
  });
  const instance = await proxy(t, server, { lifetimeMs: 100 });
  const socket = net.connect(instance.address.port, '127.0.0.1');
  socket.on('error', () => {});
  socket.once('data', upgraded.resolve);
  socket.write(upgradeText(instance));
  assert.match((await upgraded.promise).toString(), /^HTTP\/1.1 101 /);
  await instance.closed;
  await remoteClosed.promise;
  assert.deepEqual(instance.snapshot(), { closed: true, connections: 0, upstreams: 0, inFlight: 0 });
  assert.equal(server.listening, true);
  await instance.close();
});

test('fails generically when upstream is unavailable and bounds request duration and body bytes', { timeout: 5000 }, async t => {
  const unavailable = await upstream(t, (_req, res) => res.end());
  const port = unavailable.address().port;
  await new Promise(resolve => unavailable.close(resolve));
  const instance = await startMetroProxy({ ...options, upstreamPort: port });
  t.after(() => instance.close());
  const failed = await request(instance);
  assert.equal(failed.status, 502); assert.equal(failed.body.toString(), 'proxy-upstream-error');
  const server = await upstream(t, () => {});
  const bounded = await proxy(t, server, { requestTimeoutMs: 20, maxRequestBytes: 4 });
  assert.equal((await request(bounded)).status, 504);
  assert.equal((await request(bounded, { method: 'POST', body: 'too large' })).status, 413);
});

test('bounds simultaneous in-flight requests without touching another fixture', { timeout: 5000 }, async t => {
  const started = deferred();
  const server = await upstream(t, (_req, res) => { res.write('pending'); started.resolve(); });
  const instance = await proxy(t, server, { maxInFlight: 1 });
  const req = http.get({ host: '127.0.0.1', port: instance.address.port, headers: { Host: `${hostname}:${instance.address.port}` } });
  req.on('error', () => {});
  t.after(() => req.destroy());
  await started.promise;
  assert.equal((await request(instance)).status, 503);
  assert.equal(server.listening, true);
});

test('preserves a real chunked HTTP refusal to websocket upgrade', { timeout: 5000 }, async t => {
  const server = await upstream(t, (_req, res) => res.end());
  server.on('upgrade', (_req, socket) => {
    socket.end('HTTP/1.1 401 Unauthorized\r\nTransfer-Encoding: chunked\r\nSet-Cookie: synthetic=expired\r\nConnection: close\r\n\r\n4\r\nden\n\r\n3\r\nied\r\n0\r\n\r\n');
  });
  const instance = await proxy(t, server);
  const response = await request(instance, { path: '/hot', headers: { Connection: 'Upgrade', Upgrade: 'websocket', 'Sec-WebSocket-Version': '13', 'Sec-WebSocket-Key': key } });
  assert.equal(response.status, 401);
  assert.deepEqual(response.headers['set-cookie'], ['synthetic=expired']);
  assert.equal(response.body.toString(), 'den\nied');
});

test('connection capacity rejects an extra socket and permits reconnection after cleanup', { timeout: 5000 }, async t => {
  const server = await upstream(t, (_req, res) => res.end('ok'));
  const instance = await proxy(t, server, { maxConnections: 1 });
  const first = net.connect(instance.address.port, '127.0.0.1');
  first.on('error', () => {});
  await once(first, 'connect');
  const extra = net.connect(instance.address.port, '127.0.0.1');
  extra.on('error', () => {});
  await new Promise(resolve => extra.once('close', resolve));
  assert.equal(instance.snapshot().connections, 1);
  const firstClosed = new Promise(resolve => first.once('close', resolve));
  first.destroy(); await firstClosed;
  await instance.close();
  const replacement = await startMetroProxy({ ...options, port: instance.address.port, upstreamPort: server.address().port });
  t.after(() => replacement.close());
  assert.equal((await request(replacement)).body.toString(), 'ok');
});

test('rejects oversized chunked requests and invalid websocket acceptance without exposing upstream errors', { timeout: 5000 }, async t => {
  const server = await upstream(t, () => {});
  server.on('upgrade', (_req, socket) => socket.end('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: invalid\r\n\r\n'));
  const instance = await proxy(t, server, { maxRequestBytes: 4 });
  assert.equal((await request(instance, { method: 'POST', headers: { 'Transfer-Encoding': 'chunked' }, body: 'overflow' })).status, 413);
  assert.match(await raw(instance, upgradeText(instance)), /^HTTP\/1.1 502 /);
});
