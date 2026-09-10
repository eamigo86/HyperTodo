'use strict';

// Server contract tests only: Node's manual Cookie header is NOT native jar proof.
const assert = require('node:assert/strict');
const { request } = require('node:http');
const test = require('node:test');
const { createProbeServer } = require('./realtime-native-server.cjs');

async function fixture(t, options = {}) {
  const probe = createProbeServer(options);
  const address = await probe.listen();
  t.after(() => probe.close());
  const bootstrap = await fetch(`${address.baseUrl}/bootstrap`);
  const cookie = bootstrap.headers.get('set-cookie').split(';')[0];
  return { probe, address, cookie, bootstrap };
}

function api(address, cookie, path, options = {}) {
  return fetch(`${address.baseUrl}/${path}`, {
    ...options,
    headers: { Cookie: cookie, ...options.headers },
  });
}

async function readFrame(reader, state) {
  while (!state.pending.includes('\n\n')) {
    const result = await reader.read();
    assert.equal(result.done, false, 'stream ended before the next frame');
    state.pending += new TextDecoder().decode(result.value);
  }
  const end = state.pending.indexOf('\n\n');
  const frame = state.pending.slice(0, end);
  state.pending = state.pending.slice(end + 2);
  assert.match(frame, /^event: probe\ndata: /);
  return JSON.parse(frame.slice('event: probe\ndata: '.length));
}

function ack(address, cookie, token) {
  return api(address, cookie, 'ack', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  });
}

async function eventually(predicate) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  assert.fail('lifecycle observation did not arrive');
}

test('bootstrap creates a unique, scoped HttpOnly cookie without logging secrets', async (t) => {
  const logs = [];
  const one = await fixture(t, { onEvidence: (event) => logs.push(event) });
  const two = await fixture(t);
  assert.equal(one.bootstrap.status, 200);
  assert.notEqual(one.address.runPath, two.address.runPath);
  assert.notEqual(one.cookie.split('=')[0], two.cookie.split('=')[0]);
  const setCookie = one.bootstrap.headers.get('set-cookie');
  assert.match(setCookie, /; HttpOnly(?:;|$)/);
  assert.match(setCookie, /; SameSite=Strict(?:;|$)/);
  assert.ok(setCookie.includes(`; Path=${one.address.runPath}/`));
  assert.match(one.address.baseUrl, /^http:\/\/127\.0\.0\.1:\d+\/probe-[a-f0-9]{32}$/);
  assert.ok(!JSON.stringify(logs).includes(one.cookie));
  assert.deepEqual(await one.bootstrap.json(), { ok: true });
});

test('cookie checks inspect only the run cookie and reject missing, duplicate and wrong values', async (t) => {
  const { probe, address, cookie } = await fixture(t);
  for (const supplied of ['', 'unrelated=real-session', `${cookie}bad`, `${cookie}; ${cookie}`]) {
    const response = await api(address, supplied, 'stream');
    assert.equal(response.status, 403);
    assert.deepEqual(await response.json(), { error: 'forbidden' });
  }
  const report = await api(address, `unrelated=preserve-me; ${cookie}; another=untouched`, 'report');
  assert.equal(report.status, 200);
  assert.equal(probe.report().activeStreams, 0);
  assert.ok(!JSON.stringify(await report.json()).includes('preserve-me'));
});

test('second frame requires first read token; abort succeeds only after second token and server close', async (t) => {
  const { probe, address, cookie } = await fixture(t);
  const controller = new AbortController();
  const response = await api(address, cookie, 'stream', { signal: controller.signal });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'text/event-stream; charset=utf-8');
  assert.equal(response.headers.get('content-encoding'), null);
  const reader = response.body.getReader();
  const state = { pending: '' };
  const first = await readFrame(reader, state);
  assert.equal(first.stage, 1);
  assert.equal(probe.report().secondFrameSent, false);
  assert.equal((await ack(address, cookie, 'wrong')).status, 403);
  assert.equal(probe.report().secondFrameSent, false);
  assert.equal((await ack(address, cookie, first.token)).status, 204);
  const second = await readFrame(reader, state);
  assert.equal(second.stage, 2);
  assert.notEqual(first.token, second.token);
  assert.equal(probe.report().passed, false);
  assert.equal((await ack(address, cookie, second.token)).status, 204);
  assert.equal(probe.report().passed, false, 'ACK alone is not an observed connection close');
  controller.abort();
  await reader.read().catch(() => {});
  await eventually(() => probe.report().streamClosed);
  assert.equal(probe.report().passed, true);
  assert.equal(probe.report().activeStreams, 0);
  assert.equal(probe.report().closeReason, 'client');
  const report = await (await api(address, cookie, 'report')).json();
  assert.equal(report.server.passed, true);
  assert.equal(report.client, null);
  assert.ok(!JSON.stringify(report).includes(first.token));
  assert.ok(!JSON.stringify(report).includes(cookie));
});

test('stream admission is one-shot and early disconnect is not success', async (t) => {
  const { probe, address, cookie } = await fixture(t);
  const controller = new AbortController();
  const response = await api(address, cookie, 'stream', { signal: controller.signal });
  const reader = response.body.getReader();
  await readFrame(reader, { pending: '' });
  assert.equal((await api(address, cookie, 'stream')).status, 409);
  controller.abort();
  await reader.read().catch(() => {});
  await eventually(() => probe.report().streamClosed);
  assert.equal(probe.report().passed, false);
  assert.equal((await api(address, cookie, 'stream')).status, 409);
});

test('unknown route/method, ACK before stream and malformed/oversized bodies are bounded', async (t) => {
  const { address, cookie } = await fixture(t);
  assert.equal((await fetch(`${address.baseUrl}/../missing`)).status, 404);
  assert.equal((await api(address, cookie, 'bootstrap', { method: 'POST' })).status, 405);
  assert.equal((await ack(address, cookie, 'not-yet')).status, 409);
  for (const body of ['{', 'null', '[]', '{}', '{"token":3}', '{"token":"x","extra":true}']) {
    const response = await api(address, cookie, 'ack', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body,
    });
    assert.equal(response.status, 400);
  }
  assert.equal((await api(address, cookie, 'ack', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: 'x'.repeat(257),
  })).status, 413);
  assert.equal((await api(address, cookie, 'ack', { method: 'POST', body: '{}' })).status, 415);
});

test('stream deadline and explicit server cleanup cannot count as client abort', async (t) => {
  const { probe, address, cookie } = await fixture(t, { streamDeadlineMs: 30 });
  const response = await api(address, cookie, 'stream');
  await response.text().catch(() => {});
  await eventually(() => probe.report().streamClosed);
  assert.equal(probe.report().closeReason, 'deadline');
  assert.equal(probe.report().passed, false);
  assert.equal(probe.report().activeStreams, 0);
  const active = await fixture(t);
  const ongoing = await api(active.address, active.cookie, 'stream');
  await active.probe.close();
  await ongoing.text().catch(() => {});
  assert.equal(active.probe.report().closeReason, 'shutdown');
  assert.equal(active.probe.report().activeStreams, 0);
});

test('reset expires only its own cookie path and reports contain only documented fields', async (t) => {
  const { probe, address, cookie } = await fixture(t);
  const response = await api(address, `real=untouched; ${cookie}`, 'reset', { method: 'POST' });
  assert.equal(response.status, 204);
  assert.equal(response.headers.get('set-cookie'), `${cookie.split('=')[0]}=; Path=${address.runPath}/; HttpOnly; SameSite=Strict; Max-Age=0`);
  assert.deepEqual(Object.keys(probe.report()).sort(), [
    'activeStreams', 'bootstrapCount', 'closeReason', 'firstAckReceived',
    'firstFrameSent', 'passed', 'secondAckReceived', 'secondFrameSent',
    'streamAuthorized', 'streamClosed',
  ].sort());
});

test('chunked request body overflow is bounded without trusting Content-Length', async (t) => {
  const { address, cookie } = await fixture(t);
  const status = await new Promise((resolve, reject) => {
    const req = request(`${address.baseUrl}/ack`, {
      method: 'POST', headers: { Cookie: cookie, 'Content-Type': 'application/json' },
    }, (res) => { res.resume(); resolve(res.statusCode); });
    req.on('error', reject);
    req.write('x'.repeat(200)); req.end('y'.repeat(200));
  });
  assert.equal(status, 413);
});

const clientEvidence = {
  platform: 'ios', clientVersion: '57.0.9', expoVersion: '57.0.21',
  executionEnvironment: 'storeClient', reactNativeVersion: '0.86.3',
  checks: { bootstrapOk: true, firstFrameRead: true, secondFrameRead: true,
    abortRequested: true, serverCloseObserved: true },
  failedStage: null, errorCode: null,
};

function upload(address, cookie, payload) {
  return api(address, cookie, 'client-report', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

test('client self-report stays separate from server observations and is allowlisted', async (t) => {
  const { probe, address, cookie } = await fixture(t);
  assert.equal((await upload(address, cookie, clientEvidence)).status, 204);
  const report = await (await api(address, cookie, 'report')).json();
  assert.deepEqual(report.client, clientEvidence);
  assert.equal(report.server.passed, false, 'self-report cannot manufacture server evidence');
  assert.equal(probe.report().passed, false);
  const malformed = [
    { ...clientEvidence, cookie: 'do-not-store' },
    { ...clientEvidence, platform: 'web' },
    { ...clientEvidence, clientVersion: 'secret\nvalue' },
    { ...clientEvidence, checks: { ...clientEvidence.checks, token: true } },
    { ...clientEvidence, checks: { ...clientEvidence.checks, bootstrapOk: 'true' } },
    { ...clientEvidence, failedStage: 'user-sensitive-text' },
    { ...clientEvidence, errorCode: 'exception with credentials' },
  ];
  for (const body of malformed) assert.equal((await upload(address, cookie, body)).status, 400);
  const oversized = await api(address, cookie, 'client-report', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: 'x'.repeat(2049),
  });
  assert.equal(oversized.status, 413);
  assert.deepEqual((await (await api(address, cookie, 'report')).json()).client, clientEvidence);
});

test('configuration rejects unbounded timers/ports/addresses and foreign origins', async (t) => {
  for (const options of [
    { streamDeadlineMs: 0 }, { streamDeadlineMs: Infinity }, { streamDeadlineMs: 90000 },
    { lifetimeMs: -1 }, { lifetimeMs: Infinity }, { port: -1 }, { port: 65536 },
    { host: 'attacker.example' },
  ]) assert.throws(() => createProbeServer(options), /invalid probe configuration/);
  const { address, cookie } = await fixture(t);
  const response = await api(address, cookie, 'report', { headers: { Origin: 'http://foreign.example' } });
  assert.equal(response.status, 403);
  assert.equal(response.headers.get('access-control-allow-origin'), null);
});

test('CLI help is offline and invalid CLI input never creates a listener', async () => {
  const { spawnSync } = require('node:child_process');
  const file = require.resolve('./realtime-native-server.cjs');
  const help = spawnSync(process.execPath, [file, '--help'], { encoding: 'utf8', timeout: 2000 });
  assert.equal(help.status, 0);
  assert.match(help.stdout, /test-only/);
  assert.match(help.stdout, /127\.0\.0\.1/);
  assert.ok(!help.stdout.includes('"kind":"ready"'));
  const invalid = spawnSync(process.execPath, [file, '--port', 'not-a-port'], { encoding: 'utf8', timeout: 2000 });
  assert.equal(invalid.status, 1);
  assert.equal(invalid.stderr, 'probe startup failed\n');
  assert.equal(invalid.stdout, '');
});

test('CLI readiness and shutdown evidence contain no Cookie header or ACK token', async (t) => {
  const { spawn } = require('node:child_process');
  const child = spawn(process.execPath, [require.resolve('./realtime-native-server.cjs')], {
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  const lines = [];
  let pending = '';
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', (chunk) => {
    pending += chunk;
    while (pending.includes('\n')) {
      const end = pending.indexOf('\n');
      lines.push(JSON.parse(pending.slice(0, end)));
      pending = pending.slice(end + 1);
    }
  });
  const exited = new Promise((resolve) => child.once('exit', resolve));
  t.after(async () => { child.kill('SIGTERM'); await exited; });
  await eventually(() => lines.some((line) => line.kind === 'ready'));
  const ready = lines.find((line) => line.kind === 'ready');
  assert.match(ready.baseUrl, /^http:\/\/127\.0\.0\.1:/);
  const bootstrap = await fetch(`${ready.baseUrl}/bootstrap`);
  const cookie = bootstrap.headers.get('set-cookie').split(';')[0];
  const response = await api(ready, `unrelated=sensitive-marker; ${cookie}`, 'stream');
  const frame = await readFrame(response.body.getReader(), { pending: '' });
  child.kill('SIGTERM');
  await exited;
  assert.ok(lines.some((line) => line.kind === 'stream-close' && line.server.closeReason === 'shutdown'));
  const output = JSON.stringify(lines);
  for (const secret of [cookie, cookie.split('=')[1], frame.token, 'sensitive-marker']) {
    assert.ok(!output.includes(secret));
  }
});

test('fixture cookie expires after 120 seconds even when native cleanup cannot run', async (t) => {
  const { address, cookie, bootstrap } = await fixture(t);
  const issued = bootstrap.headers.get('set-cookie');
  assert.ok(/; Max-Age=120(?:;|$)/.test(issued), 'fixture cookie must advertise Max-Age=120');
  assert.equal(issued.match(/Max-Age=/g).length, 1);
  const reset = await api(address, cookie, 'reset', { method: 'POST' });
  const expired = reset.headers.get('set-cookie');
  assert.match(expired, /; Max-Age=0(?:;|$)/);
  assert.equal(expired.match(/Max-Age=/g).length, 1);
  assert.ok(expired.includes(`; Path=${address.runPath}/`));
});
