'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createReporter } = require('./report.cjs');
const run = 'a'.repeat(32), part = { case: 'lifecycle', kind: 'paused' };
const turn = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
// Optional calls preserve meaningful admission/order assertions on the old baseline.
function active(reporter, value = true) { reporter.setActive?.(value); }
function cleanup(t, reporter) { t.after(() => reporter.dispose?.()); return reporter; }
function clock() {
  const jobs = new Set();
  return { setTimeout(fn, ms) { assert.equal(ms, 2000); jobs.add(fn); return fn; }, clearTimeout(fn) { jobs.delete(fn); }, expire() { for (const fn of [...jobs]) fn(); }, size: () => jobs.size };
}
test('inactive by default: queued inactive/background records upload only after active', async t => {
  const calls = [], reporter = cleanup(t, createReporter(run, 'ios', async record => { calls.push(record); return 204; }));
  reporter.send(part); active(reporter, false); reporter.send(part);
  await turn(); assert.equal(calls.length, 0);
  active(reporter); await reporter.settled();
  assert.deepEqual(calls.map(r => r.sequence), [1, 2]);
});
test('lost ACK retries the identical immutable head, then advances only after 204', async t => {
  const calls = [], persisted = [], reply = deferred();
  const reporter = cleanup(t, createReporter(run, 'ios', async record => {
    calls.push(record);
    if (calls.length === 1) { persisted.push(record); throw new Error('synthetic lost ACK'); }
    if (calls.length === 2) { assert.deepEqual(record, persisted.at(-1)); return reply.promise; }
    persisted.push(record); return 204;
  }));
  active(reporter); reporter.send(part); reporter.send({ case: 'lifecycle', kind: 'foreground' });
  await turn(); assert.equal(calls.length, 2); assert.equal(calls[0], calls[1]); assert.ok(Object.isFrozen(calls[0]));
  assert.deepEqual(persisted.map(r => r.sequence), [1]);
  reply.resolve(204); await reporter.settled();
  assert.deepEqual(calls.map(r => r.sequence), [1, 1, 2]);
  assert.deepEqual(persisted.map(r => r.sequence), [1, 2]);
  assert.equal(reporter.snapshot().state, 'recording');
});
test('pause preserves in-flight ACK, but defers the following head without abort', async t => {
  const reply = deferred(), calls = [], signals = [];
  const reporter = cleanup(t, createReporter(run, 'ios', (record, signal) => { calls.push(record); signals.push(signal); return calls.length === 1 ? reply.promise : Promise.resolve(204); }));
  active(reporter); reporter.send(part); reporter.send(part); await turn(); active(reporter, false);
  reply.resolve(204); await turn();
  assert.equal(calls.length, 1); assert.equal(signals[0].aborted, false);
  active(reporter); await reporter.settled(); assert.equal(calls.length, 2);
});
test('timeout settles even when upload ignores abort; late 204 cannot rescue exhausted head', async t => {
  const timer = clock(), replies = [deferred(), deferred()], signals = [];
  const reporter = cleanup(t, createReporter(run, 'ios', (_record, signal) => { signals.push(signal); return replies[signals.length - 1].promise; }, timer));
  active(reporter); reporter.send(part); await turn(); timer.expire(); await turn();
  assert.equal(signals.length, 2); assert.equal(signals[0].aborted, true);
  timer.expire(); await reporter.settled();
  assert.equal(reporter.snapshot().reason, 'report-failed'); assert.equal(timer.size(), 0);
  replies.forEach(reply => reply.resolve(204)); await turn();
  active(reporter, false); active(reporter); assert.equal(signals.length, 2);
  assert.equal(await reporter.complete(), 'inconclusive');
});
test('pause/resume never resets the two-attempt budget', async t => {
  const calls = [], replies = [deferred(), deferred()];
  const reporter = cleanup(t, createReporter(run, 'ios', record => { calls.push(record); return replies[calls.length - 1].promise; }));
  active(reporter); reporter.send(part); await turn(); active(reporter, false);
  replies[0].reject(new Error('controlled transport')); await turn(); assert.equal(calls.length, 1);
  active(reporter); await turn(); assert.equal(calls.length, 2);
  active(reporter, false); active(reporter); active(reporter, false);
  replies[1].reject(new Error('controlled transport')); await reporter.settled();
  active(reporter); await turn(); assert.equal(calls.length, 2); assert.equal(reporter.snapshot().state, 'inconclusive');
});
for (const status of [400, 500, 200]) test(`HTTP ${status} is definitive: no retry or advancement`, async t => {
  let calls = 0;
  const reporter = cleanup(t, createReporter(run, 'ios', async () => { calls++; return status; }));
  active(reporter); reporter.send(part); reporter.send(part); await reporter.settled();
  assert.equal(calls, 1); assert.equal(reporter.snapshot().reason, 'report-failed');
});
test('complete seals producer admission immediately and retries only its final marker', async t => {
  const calls = [], reply = deferred();
  const reporter = cleanup(t, createReporter(run, 'ios', record => { calls.push(record); return calls.length === 1 ? Promise.reject(new Error('lost final ACK')) : reply.promise; }));
  active(reporter); const finish = reporter.complete();
  assert.equal(reporter.send(part), false); await turn();
  assert.deepEqual(calls.map(r => [r.sequence, r.kind]), [[1, 'complete'], [1, 'complete']]);
  assert.equal(reporter.snapshot().state, 'recording'); active(reporter, false); active(reporter);
  assert.equal(reporter.send({ case: 'lifecycle', kind: 'foreground' }), false);
  reply.resolve(204); assert.equal(await finish, 'complete'); assert.equal(await reporter.complete(), 'complete');
  assert.equal(calls.length, 2); assert.equal(reporter.records().length, 1);
});
for (const inFlight of [false, true]) test(`dispose settles ${inFlight ? 'in-flight' : 'inactive'} work without fabricating ACK`, async t => {
  const timer = clock(), reply = deferred(); let signal;
  const reporter = cleanup(t, createReporter(run, 'ios', (_record, value) => { signal = value; return reply.promise; }, timer));
  active(reporter, inFlight); reporter.send(part); await turn();
  const finish = reporter.complete(); reporter.dispose?.();
  // Assert synchronously before awaiting so the old missing-dispose baseline cannot hang.
  assert.equal(reporter.snapshot().state, 'inconclusive');
  assert.equal(await finish, 'inconclusive'); assert.equal(timer.size(), 0);
  if (inFlight) assert.equal(signal.aborted, true);
  reply.resolve(204); await turn(); assert.equal(reporter.snapshot().state, 'inconclusive');
});
