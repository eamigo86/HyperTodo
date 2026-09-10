'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const net = require('node:net');
const { once } = require('node:events');
const { createHash } = require('node:crypto');
const { startAndroidSystemProxy } = require('./android-system-proxy.cjs');
const { startMetroProxy } = require('./metro-proxy.cjs');
const id = 'b'.repeat(32), api = `hvt-${id}.local:49991`, metroHost = `hvtm-${id}.local`;
async function server(t, handler) {
  const s = http.createServer(handler), sockets = new Set();
  s.on('connection', c => { sockets.add(c); c.on('close', () => sockets.delete(c)); });
  s.listen(0, '127.0.0.1'); await once(s, 'listening');
  t.after(async () => { for (const c of sockets) c.destroy(); await new Promise(r => s.close(r)); });
  return s;
}
function request(p, path, headers = {}, body = undefined) {
  return new Promise((resolve, reject) => {
    const r = http.request({ host: '127.0.0.1', port: p.address.port, path, method: body ? 'POST' : 'GET', headers: { Host: api, ...headers } }, s => {
      const chunks = []; s.on('data', c => chunks.push(c)); s.on('end', () => resolve({ status: s.statusCode, headers: s.headers, body: Buffer.concat(chunks).toString() }));
    }); r.on('error', reject); r.end(body);
  });
}
async function raw(p, text) {
  const socket = net.connect(p.address.port, '127.0.0.1'), chunks = [];
  socket.on('data', c => chunks.push(c)); socket.on('error', () => {});
  socket.write(text); await once(socket, 'close'); return Buffer.concat(chunks).toString();
}
async function setup(t, handler = (_q, r) => r.end('ok')) {
  const upstream = await server(t, handler);
  const m = await startMetroProxy({ bindAddress: '127.0.0.1', port: 0, hostname: metroHost, upstreamAddress: '127.0.0.1', upstreamPort: upstream.address().port });
  t.after(() => m.close());
  const config = { port: 0, lifetimeMs: 10000, api: { authority: api, upstreamPort: upstream.address().port }, metro: { authority: `${metroHost}:${m.address.port}`, upstreamPort: m.address.port } };
  const p = await startAndroidSystemProxy(config); t.after(() => p.close());
  return { p, config, upstream };
}
test('absolute HTTP preserves canonical path, method, cookies, body and response', async t => {
  let seen;
  const { p } = await setup(t, (q, r) => { let body = ''; q.on('data', c => body += c); q.on('end', () => {
    seen = { url: q.url, method: q.method, cookie: q.headers.cookie, host: q.headers.host, body };
    r.writeHead(422, { 'Set-Cookie': ['own=one; HttpOnly', 'other=two'], 'Content-Type': 'text/xml' }); r.end('<error/>');
  }); });
  const got = await request(p, `http://${api}/hv/login/?x=%2f&x=+`, { Cookie: 'synthetic=only' }, 'x=1&x=2&csrf=synthetic');
  assert.equal(got.status, 422); assert.equal(got.body, '<error/>');
  assert.deepEqual(got.headers['set-cookie'], ['own=one; HttpOnly', 'other=two']);
  assert.deepEqual(seen, { url: '/hv/login/?x=%2f&x=+', method: 'POST', cookie: 'synthetic=only', host: api, body: 'x=1&x=2&csrf=synthetic' });
  assert.equal(p.address.address, '127.0.0.1');
});
test('rejects foreign/credential/conflicting/ambiguous authorities before upstream I/O', async t => {
  let calls = 0; const { p } = await setup(t, (_q, r) => { calls++; r.end(); });
  for (const url of [`http://foreign.invalid/`, `http://user:pass@${api}/`, `https://${api}/`, `http://${api}/#fragment`, `http://${api}/bad\\path`]) {
    assert.equal((await request(p, url)).status, 403);
  }
  assert.equal((await request(p, `http://${api}/`, { Host: 'other.local' })).status, 403);
  assert.equal((await request(p, `http://${api}/`, { 'Proxy-Authorization': 'synthetic-only' })).status, 403);
  assert.match(await raw(p, `GET http://${api}/ HTTP/1.1\r\nHost: ${api}\r\nHost: ${api}\r\n\r\n`), /^HTTP\/1.1 403 /);
  assert.match(await raw(p, `CONNECT ${api} HTTP/1.1\r\nHost: ${api}\r\n\r\n`), /^HTTP\/1.1 405 /);
  assert.equal(calls, 0);
});
test('configuration cannot select arbitrary hosts/upstreams or disable finite bounds', async t => {
  const { config } = await setup(t);
  for (const bad of [{ port: 8081 }, { lifetimeMs: 600001 }, { lifetimeMs: 0 }, { api: { ...config.api, upstreamAddress: '8.8.8.8' } }, { api: { ...config.api, upstreamPort: 8081 } }, { api: { ...config.api, authority: 'example.com:80' } }, { metro: { ...config.metro, authority: `hvtm-${'c'.repeat(32)}.local:1234` } }]) {
    await assert.rejects(startAndroidSystemProxy({ ...config, ...bad }), /invalid-system-proxy-config/);
  }
});
test('supports only Metro allowlisted Upgrade paths via existing strict proxy', async t => {
  const { p, config, upstream } = await setup(t);
  upstream.on('upgrade', (_q, s) => s.end('HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n'));
  const header = a => `Host: ${a}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n`;
  assert.match(await raw(p, `GET http://${api}/hot HTTP/1.1\r\n${header(api)}`), /^HTTP\/1.1 403 /);
  assert.match(await raw(p, `GET http://${config.metro.authority}/foreign HTTP/1.1\r\n${header(config.metro.authority)}`), /^HTTP\/1.1 403 /);
  assert.match(await raw(p, `GET http://${config.metro.authority}/hot?platform=android HTTP/1.1\r\n${header(config.metro.authority)}`), /^HTTP\/1.1 403 /);
  assert.equal(p.snapshot().metro, 1); // The genuine upstream refusal was preserved.
});
test('bounds request bodies and closes every owned socket idempotently', async t => {
  const { p } = await setup(t);
  assert.equal((await request(p, `http://${api}/`, { 'Content-Length': '1048577' })).status, 413);
  await p.close(); await p.close(); await p.closed;
  assert.deepEqual(p.snapshot(), { closed: true, connections: 0, inFlight: 0, api: 0, metro: 0 });
});
test('passes actual Metro websocket acceptance and bytes without buffering or arbitrary Upgrade', async t => {
  const { p, config, upstream } = await setup(t);
  const key = 'dGhlIHNhbXBsZSBub25jZQ==';
  const accept = createHash('sha1').update(key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  const frame = Buffer.from([0x81, 1, 0x78]);
  upstream.on('upgrade', (req, socket) => {
    assert.equal(req.url, '/hot?platform=android');
    socket.end(Buffer.concat([Buffer.from(`HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`), frame]));
  });
  const text = await raw(p, `GET http://${config.metro.authority}/hot?platform=android HTTP/1.1\r\nHost: ${config.metro.authority}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: ${key}\r\n\r\n`);
  assert.match(text, /^HTTP\/1.1 101 /); assert.ok(text.endsWith(frame.toString()));
});
test('reserves upstream capacity before admitting a request at 64 total sockets', async t => {
  let calls = 0;
  const { p } = await setup(t, (_req, res) => { calls++; res.end('ok'); });
  const idle = [];
  t.after(() => { for (const socket of idle) socket.destroy(); });
  for (let n = 0; n < 63; n++) {
    const socket = net.connect(p.address.port, '127.0.0.1');
    idle.push(socket); await once(socket, 'connect');
  }
  const response = await request(p, `http://${api}/`);
  assert.equal(response.status, 503);
  assert.equal(calls, 0);
  assert.ok(p.snapshot().connections <= 64);
});
