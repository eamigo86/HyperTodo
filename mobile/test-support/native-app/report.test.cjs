'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  validateRecord,
  createReporter
} = require('./report.cjs');
const run = 'a'.repeat(32);
const record = (overrides = {}) => ({
  v: 1,
  run,
  sequence: 1,
  platform: 'ios',
  case: 'startup',
  kind: 'ready',
  operation: null,
  route: 1,
  outcome: null,
  reason: null,
  ...overrides
});
test('accepts immutable bounded ready and matching terminal records', () => {
  const ready = validateRecord(record(), run, 1);
  assert.ok(Object.isFrozen(ready));
  assert.deepEqual(ready, record());
  assert.equal(validateRecord(record({
    kind: 'terminal',
    operation: 'gate-1-0-2',
    outcome: 'ack',
    reason: 'reload-layout'
  }), run, 1).outcome, 'ack');
});
for (const [label, change] of Object.entries({
  unknown: {
    secret: 'no'
  },
  run: {
    run: 'b'.repeat(32)
  },
  sequence: {
    sequence: 2
  },
  bool: {
    sequence: true
  },
  platform: {
    platform: 'web'
  },
  freeText: {
    reason: 'actual secret'
  },
  route: {
    route: 257
  },
  operation: {
    kind: 'http-get',
    route: null,
    operation: 'https://secret/'
  },
  readyOutcome: {
    outcome: 'ack'
  },
  terminalMissing: {
    kind: 'terminal'
  },
  httpRoute: {
    kind: 'http-get',
    operation: 'gate-1-0-1'
  },
  tooLong: {
    operation: 'gate-' + '1'.repeat(78) + '-0-1'
  }
})) {
  test(`rejects invalid ${label} without returning input`, () => assert.throws(() => validateRecord(record(change), run, 1), /invalid-record/));
}
test('rejects oversize/invalid JSON and accepts exactly ten keys only', () => {
  assert.throws(() => validateRecord(' '.repeat(2049), run, 1), /invalid-record/);
  assert.throws(() => validateRecord('{', run, 1), /invalid-record/);
  assert.deepEqual(validateRecord(JSON.stringify(record()), run, 1), record());
});
test('reporter serializes uploads, freezes records and complete is not a PASS claim', async () => {
  let release;
  const first = new Promise(resolve => {
    release = resolve;
  });
  const seen = [];
  const reporter = createReporter(run, 'ios', async value => {
    seen.push(value);
    if (seen.length === 1) await first;
    return 204;
  });
  reporter.setActive(true);
  reporter.send({
    case: 'startup',
    kind: 'ready',
    route: 1
  });
  reporter.send({
    case: 'resources',
    kind: 'hint'
  });
  await Promise.resolve();
  assert.equal(seen.length, 1);
  release();
  await reporter.settled();
  assert.deepEqual(seen.map(value => value.sequence), [1, 2]);
  assert.ok(Object.isFrozen(seen[0]));
  await reporter.complete();
  assert.equal(reporter.snapshot().state, 'complete');
  assert.equal(seen.at(-1).kind, 'complete');
  assert.equal(JSON.stringify(seen).includes('PASS'), false);
});
test('HTTP rejection makes evidence persistently inconclusive without retry', async () => {
  let calls = 0;
  const reporter = createReporter(run, 'android', async () => {
    calls++;
    return 400;
  });
  reporter.setActive(true);
  reporter.send({
    case: 'startup',
    kind: 'ready',
    route: 1
  });
  await reporter.settled();
  reporter.send({
    case: 'auth',
    kind: 'hint'
  });
  await reporter.complete();
  assert.equal(calls, 1);
  assert.deepEqual(reporter.snapshot(), {
    state: 'inconclusive',
    reason: 'report-failed',
    records: 2
  });
  assert.equal(JSON.stringify(reporter.records()).includes('secret'), false);
});
test('invalid local event and overflow cannot truncate into complete', async () => {
  const invalid = createReporter(run, 'ios', async () => 204);
  assert.equal(invalid.send({
    case: 'auth',
    kind: 'hint',
    token: 'secret'
  }), false);
  assert.equal(invalid.snapshot().reason, 'invalid-record');
  const full = createReporter(run, 'ios', async () => 204);
  for (let i = 0; i < 500; i++) assert.equal(full.send({
    case: 'resources',
    kind: 'hint'
  }), true);
  assert.equal(full.send({
    case: 'resources',
    kind: 'hint'
  }), false);
  await full.complete();
  assert.deepEqual(full.snapshot(), {
    state: 'inconclusive',
    reason: 'overflow',
    records: 500
  });
});
test('checks the frozen cross-language contract vectors', () => {
  const vectors = require('./report-vectors.json');
  for (const value of vectors.valid) assert.deepEqual(validateRecord(value, vectors.run, vectors.sequence), value);
  for (const value of vectors.invalid) assert.throws(() => validateRecord(value, vectors.run, vectors.sequence), /invalid-record/);
});
