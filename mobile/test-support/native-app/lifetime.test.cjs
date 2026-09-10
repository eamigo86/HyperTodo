'use strict';

const test = require('node:test'),
  assert = require('node:assert/strict');
const {
  createFixtureLifetime
} = require('./lifetime.cjs');
const pending = () => {
  let resolve;
  const promise = new Promise(yes => {
    resolve = yes;
  });
  return {
    promise,
    resolve
  };
};
test('drains admitted credential/theme writes before clearing only the injected keys', async () => {
  const held = pending(),
    calls = [];
  let tail = Promise.resolve();
  const credentials = {
    read: async () => null,
    storage: {
      enqueue: job => {
        const next = tail.then(() => job({
          save: async () => {
            calls.push('credential-write');
            await held.promise;
          },
          clear: async () => {
            calls.push('credential-clear');
          }
        }));
        tail = next.catch(() => {});
        return next;
      }
    }
  };
  const theme = {
    read: () => null,
    write: async () => {
      calls.push('theme-write');
      await held.promise;
    },
    clear: async () => {
      calls.push('theme-clear');
    }
  };
  const life = createFixtureLifetime(credentials, theme);
  void life.credentials.storage.enqueue(store => store.save('synthetic'));
  life.theme.write('dark');
  await Promise.resolve();
  const cleanup = life.finish();
  await Promise.resolve();
  assert.equal(calls.some(x => x.endsWith('clear')), false);
  await assert.rejects(life.credentials.storage.enqueue(async () => {}), /fixture-closed/);
  assert.throws(() => life.theme.write('light'), /fixture-closed/);
  held.resolve();
  assert.equal(await cleanup, true);
  assert.deepEqual(calls.sort(), ['credential-clear', 'credential-write', 'theme-clear', 'theme-write'].sort());
  assert.equal(await life.finish(), true);
});
test('unsettled cleanup is INCONCLUSIVE rather than deleting before a late admitted write', async () => {
  let timeout;
  const held = pending(),
    clears = [];
  const credentials = {
    read: async () => null,
    storage: {
      enqueue: async job => job({
        save: () => held.promise,
        clear: async () => {
          clears.push('credential');
        }
      })
    }
  };
  const life = createFixtureLifetime(credentials, {
    read: () => null,
    write: async () => {},
    clear: async () => {
      clears.push('theme');
    }
  }, {
    setTimeout: fn => {
      timeout = fn;
      return 1;
    },
    clearTimeout: () => {}
  });
  void life.credentials.storage.enqueue(store => store.save('synthetic'));
  const cleanup = life.finish();
  timeout();
  assert.equal(await cleanup, false);
  assert.deepEqual(clears, []);
  held.resolve();
});
