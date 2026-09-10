'use strict';

/** Test-only latency of the original Response. Never substitutes body, headers or identity. */
function createResponseHold(http, observe, clock = {
  setTimeout,
  clearTimeout
}) {
  let state = 'idle',
    method = null,
    lease = null,
    disposed = false;
  const emit = event => {
    try {
      observe(Object.freeze(event));
    } catch {/* Passive fixture observation. */}
  };
  const abort = () => Object.assign(new Error('cancelled'), {
    name: 'AbortError'
  });
  const finish = reason => {
    if (!lease) return false;
    const current = lease;
    lease = null;
    state = disposed ? 'disposed' : 'idle';
    clock.clearTimeout(current.timer);
    current.signal?.removeEventListener('abort', current.abort);
    if (reason) current.reject(reason);else {
      emit({
        kind: 'released',
        operation: current.id
      });
      current.resolve(current.response);
    }
    return true;
  };
  return Object.freeze({
    arm(value) {
      if (disposed || state !== 'idle' || !['get', 'post'].includes(value)) return false;
      method = value;
      state = 'armed';
      return true;
    },
    snapshot: () => state,
    release: () => state === 'held' && finish(),
    dispose() {
      disposed = true;
      state = 'disposed';
      finish(abort());
    },
    async fetch(input, init) {
      if (disposed) throw abort();
      const headers = new Headers(init?.headers),
        id = headers.get('X-HyperTodo-Request-ID');
      const validId = id && /^gate-(?:0|[1-9][0-9]*)-(?:0|[1-9][0-9]*)-(?:0|[1-9][0-9]*)$/.test(id) && id.length <= 80 ? id : null;
      const verb = (init?.method || 'get').toLowerCase();
      const own = state === 'armed' && method === verb && validId;
      if (own) state = 'waiting';
      if (validId && ['get', 'post'].includes(verb)) emit({
        kind: `http-${verb}`,
        operation: validId
      });
      let response;
      try {
        response = await http(input, init);
      } catch (error) {
        if (own && !disposed) state = 'idle';
        emit({
          kind: 'diagnostic',
          reason: 'request-failed'
        });
        throw error;
      }
      if (validId) emit({
        kind: 'http-response',
        operation: validId
      });
      if (disposed || init?.signal?.aborted) throw abort();
      if (!own) return response;
      return new Promise((resolve, reject) => {
        const current = {
          resolve,
          reject,
          response,
          id: validId,
          signal: init?.signal,
          abort: () => finish(abort()),
          timer: null
        };
        lease = current;
        state = 'held';
        current.signal?.addEventListener('abort', current.abort, {
          once: true
        });
        current.timer = clock.setTimeout(() => {
          emit({
            kind: 'inconclusive',
            reason: 'hold-timeout'
          });
          finish(new Error('hold-timeout'));
        }, 30000);
        emit({
          kind: 'held',
          operation: validId
        });
      });
    }
  });
}
module.exports = {
  createResponseHold
};
