'use strict';

/** Close admission, drain the same injected queue, then clear only its own credentials/theme. */
function createFixtureLifetime(original, themeIO, clock = {
  setTimeout,
  clearTimeout
}) {
  let closed = false,
    completion;
  const pending = new Set();
  function track(promise) {
    const value = Promise.resolve(promise);
    pending.add(value);
    void value.then(() => pending.delete(value), () => pending.delete(value));
    return value;
  }
  const credentials = Object.freeze({
    read: () => closed ? Promise.reject(new Error('fixture-closed')) : original.read(),
    storage: {
      enqueue: job => closed ? Promise.reject(new Error('fixture-closed')) : track(original.storage.enqueue(job))
    }
  });
  const theme = Object.freeze({
    read: () => {
      if (closed) throw new Error('fixture-closed');
      return themeIO.read();
    },
    write: name => {
      if (closed) throw new Error('fixture-closed');
      void track(themeIO.write(name)).catch(() => {});
    }
  });
  return Object.freeze({
    credentials,
    theme,
    finish() {
      if (completion) return completion;
      closed = true;
      completion = (async () => {
        let expired = false,
          timer;
        const deadline = new Promise(resolve => {
          timer = clock.setTimeout(() => {
            expired = true;
            resolve(false);
          }, 10000);
        });
        const settle = (async () => {
          await Promise.allSettled([...pending]);
          if (expired) return false;
          await Promise.all([original.storage.enqueue(store => store.clear()), themeIO.clear()]);
          return !expired;
        })().catch(() => false);
        const result = await Promise.race([settle, deadline]);
        clock.clearTimeout(timer);
        return result;
      })();
      return completion;
    }
  });
}
module.exports = {
  createFixtureLifetime
};
