'use strict';

const {
  test
} = require('node:test');
const assert = require('node:assert/strict');
const {
  createResponseHold
} = require('./hold.cjs');
const init = {
  method: 'POST',
  headers: {
    'X-HyperTodo-Request-ID': 'gate-1-0-2'
  }
};
function pending() {
  let resolve;
  const promise = new Promise(yes => {
    resolve = yes;
  });
  return {
    resolve,
    promise
  };
}
test('holds only a correlated matching genuine Response and releases identical object once', async () => {
  const response = new Response('real native body'),
    events = [];
  let calls = 0;
  const hold = createResponseHold(async () => {
    calls++;
    return response;
  }, event => events.push(event));
  assert.equal(hold.arm('post'), true);
  const request = hold.fetch('http://hvt.local/hv/tasks/', init);
  await Promise.resolve();
  assert.equal(hold.snapshot(), 'held');
  assert.equal(calls, 1);
  assert.equal(hold.release(), true);
  assert.equal(hold.release(), false);
  assert.equal(await request, response);
  assert.equal(await response.text(), 'real native body');
  assert.deepEqual(events.map(e => e.kind), ['http-post', 'http-response', 'held', 'released']);
});
test('does not hold confirmation/report/unrelated requests or rearm an occupied lease', async () => {
  const response = new Response('');
  const hold = createResponseHold(async () => response, () => {});
  hold.arm('post');
  assert.equal(await hold.fetch('http://hvt.local/hv/session-state/', {}), response);
  assert.equal(hold.snapshot(), 'armed');
  assert.equal(hold.arm('get'), false);
  hold.dispose();
  assert.equal(hold.arm('get'), false);
});
test('abort/dispose truthfully rejects held delivery without claiming rollback or ACK', async () => {
  const controller = new AbortController(),
    response = new Response('');
  const events = [];
  const hold = createResponseHold(async () => response, event => events.push(event));
  hold.arm('post');
  const request = hold.fetch('http://hvt.local/hv/tasks/', {
    ...init,
    signal: controller.signal
  });
  await Promise.resolve();
  controller.abort();
  await assert.rejects(request, {
    name: 'AbortError'
  });
  assert.equal(hold.release(), false);
  assert.equal(events.some(e => e.outcome === 'ack'), false);
  hold.dispose();
});
test('a deterministic deadline is failure only and cannot synthesize transport success', async () => {
  let timeout;
  const events = [];
  const hold = createResponseHold(async () => new Response(''), e => events.push(e), {
    setTimeout: fn => {
      timeout = fn;
      return 1;
    },
    clearTimeout: () => {}
  });
  hold.arm('post');
  const request = hold.fetch('http://hvt.local/hv/tasks/', init);
  await Promise.resolve();
  timeout();
  await assert.rejects(request, /hold-timeout/);
  assert.equal(events.at(-1).reason, 'hold-timeout');
  assert.equal(hold.release(), false);
});
test('cannot transfer a disposed pending fetch to a new hold', async () => {
  const pendingResponse = pending(),
    hold = createResponseHold(() => pendingResponse.promise, () => {});
  hold.arm('post');
  const request = hold.fetch('http://hvt.local/hv/tasks/', init);
  hold.dispose();
  pendingResponse.resolve(new Response('late'));
  await assert.rejects(request, {
    name: 'AbortError'
  });
  assert.equal(hold.snapshot(), 'disposed');
});
test('preserves the original native rejection including AbortError without recording its text', async () => {
  const original = Object.assign(new Error('private network context'), {
      name: 'AbortError'
    }),
    events = [];
  const hold = createResponseHold(async () => {
    throw original;
  }, event => events.push(event));
  await assert.rejects(hold.fetch('http://hvt.local/hv/tasks/', init), error => error === original);
  assert.equal(JSON.stringify(events).includes('private'), false);
});
