'use strict';

// Test-only evidence contract. The backend validates its own independent copy.
const CASES = Object.freeze(['startup', 'auth', 'resources', 'form', 'append-race', 'post-race', 'lifecycle', 'refusal', 'cleanup']);
const KINDS = Object.freeze(['ready', 'terminal', 'http-get', 'http-post', 'http-response', 'held', 'released', 'hint', 'paused', 'foreground', 'diagnostic', 'cleanup', 'complete', 'inconclusive']);
const OUTCOMES = Object.freeze(['ack', 'no-document', 'error', 'cancelled', 'dropped']);
const TERMINAL_REASONS = Object.freeze(['owner-unavailable', 'sync-drop', 'sync-replaced', 'sdk-on-end', 'once', 'missing-target', 'removed-delayed-origin', 'missing-local-source', 'parser-no-op', 'empty-response', 'request-error', 'local-layout', 'remote-layout', 'caller-error', 'uncorrelated-result', 'reload-layout', 'unsupported-document', 'navigation-changed', 'navigation-no-op', 'missing-destination', 'auth-transition', 'auth-panel-layout', 'auth-refused', 'auth-busy', 'auth-uncertain']);
const DIAGNOSTICS = Object.freeze(['sdk-error', 'request-failed', 'hold-timeout', 'report-failed', 'overflow', 'invalid-record', 'cleanup-failed']);
const KEYS = Object.freeze(['v', 'run', 'sequence', 'platform', 'case', 'kind', 'operation', 'route', 'outcome', 'reason']);
const RUN = /^[a-f0-9]{32}$/;
const ID = /^gate-(?:0|[1-9][0-9]*)-(?:0|[1-9][0-9]*)-(?:0|[1-9][0-9]*)$/;
const fail = () => {
  throw new Error('invalid-record');
};
const integer = (n, min, max) => Number.isSafeInteger(n) && n >= min && n <= max;
function bytes(text) {
  return new TextEncoder().encode(text).byteLength;
}
/** Validate without returning unknown fields or free-form strings. */
function validateRecord(input, run, sequence) {
  let data = input;
  try {
    if (typeof input === 'string') {
      if (bytes(input) > 2048) fail();
      data = JSON.parse(input);
    }
    if (!data || Array.isArray(data) || typeof data !== 'object' || Object.keys(data).length !== KEYS.length || !KEYS.every(key => Object.hasOwn(data, key))) fail();
    if (bytes(JSON.stringify(data)) > 2048 || !RUN.test(run) || data.v !== 1 || data.run !== run || !integer(sequence, 1, 500) || data.sequence !== sequence || !['ios', 'android'].includes(data.platform) || !CASES.includes(data.case) || !KINDS.includes(data.kind)) fail();
    if (data.operation !== null && (typeof data.operation !== 'string' || data.operation.length > 80 || !ID.test(data.operation))) fail();
    if (data.route !== null && !integer(data.route, 1, 256)) fail();
    if (data.outcome !== null && !OUTCOMES.includes(data.outcome)) fail();
    if (data.kind === 'ready') {
      if (data.route === null || data.operation !== null || data.outcome !== null || data.reason !== null) fail();
    } else if (data.kind === 'terminal') {
      if (data.route === null || data.outcome === null || !TERMINAL_REASONS.includes(data.reason)) fail();
      if (data.outcome === 'ack' && !['local-layout', 'remote-layout', 'reload-layout', 'auth-panel-layout'].includes(data.reason)) fail();
    } else {
      if (data.route !== null || data.outcome !== null) fail();
      if (['http-get', 'http-post', 'http-response', 'held', 'released'].includes(data.kind)) {
        if (data.reason !== null) fail();
      } else if (data.operation !== null) fail();
      if (['diagnostic', 'inconclusive'].includes(data.kind)) {
        if (!DIAGNOSTICS.includes(data.reason)) fail();
      } else if (data.reason !== null) fail();
    }
    return Object.freeze(Object.fromEntries(KEYS.map(key => [key, data[key]])));
  } catch {
    fail();
  }
}
/** Ordered, active-only evidence delivery; two transport attempts per frozen head. */
function createReporter(run, platform, upload, clock = { setTimeout, clearTimeout }) {
  if (!RUN.test(run) || !['ios', 'android'].includes(platform) || typeof upload !== 'function') fail();
  let state = 'recording', reason = null, active = false, closing = false,
    disposed = false, halted = false, running = false, acknowledged = 0,
    attempts = 0, cancelAttempt = null, completion;
  const records = [], waiters = new Set();
  const inconclusive = code => {
    state = 'inconclusive';
    reason ??= code;
  };
  const settle = () => {
    if (running || (!halted && acknowledged < records.length)) return;
    for (const resolve of waiters) resolve();
    waiters.clear();
  };
  const stop = code => {
    halted = true;
    inconclusive(code);
    cancelAttempt?.();
    settle();
  };
  /** A deadline is failure, never ACK; late results cannot settle another attempt. */
  async function attempt(record) {
    const abort = new AbortController();
    let timer, cancel;
    const interrupted = new Promise((_, reject) => {
      cancel = () => { reject(new Error('report-failed')); abort.abort(); };
      timer = clock.setTimeout(cancel, 2000);
    });
    cancelAttempt = cancel;
    try {
      return await Promise.race([upload(record, abort.signal), interrupted]);
    } finally {
      clock.clearTimeout(timer);
      cancelAttempt = null;
    }
  }
  async function drain() {
    if (running || halted || !active) return;
    running = true;
    try {
      while (active && !halted && acknowledged < records.length) {
        attempts++;
        try {
          const status = await attempt(records[acknowledged]);
          if (halted) break;
          if (status !== 204) { stop('report-failed'); break; }
          acknowledged++;
          attempts = 0;
        } catch {
          if (!halted && attempts >= 2) stop('report-failed');
        }
      }
    } finally {
      running = false;
      settle();
    }
  }
  function append(part) {
    if (records.length >= 500) { stop('overflow'); return false; }
    let value;
    try {
      const fields = ['case', 'kind', 'operation', 'route', 'outcome', 'reason'];
      if (!part || Object.keys(part).some(key => !fields.includes(key))) fail();
      value = validateRecord({
        v: 1, run, sequence: records.length + 1, platform,
        case: part.case, kind: part.kind, operation: part.operation ?? null,
        route: part.route ?? null, outcome: part.outcome ?? null, reason: part.reason ?? null
      }, run, records.length + 1);
    } catch {
      stop('invalid-record');
      return false;
    }
    records.push(value);
    // A valid failure diagnostic must still reach the collector when possible.
    if (value.kind === 'inconclusive') inconclusive(value.reason);
    void drain();
    return true;
  }
  function settled() {
    if (!running && (halted || acknowledged === records.length)) return Promise.resolve();
    return new Promise(resolve => waiters.add(resolve));
  }
  return Object.freeze({
    send: part => !closing && !disposed && append(part),
    setActive(value) {
      active = value === true && !disposed;
      if (active) void drain();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      closing = true;
      active = false;
      if (state !== 'complete') stop('report-failed');
    },
    settled,
    records: () => Object.freeze([...records]),
    snapshot: () => Object.freeze({ state, reason, records: records.length }),
    complete() {
      if (completion) return completion;
      // Seal before awaiting: lifecycle notifications must never follow complete.
      closing = true;
      if (state === 'recording') append({ case: 'cleanup', kind: 'complete' });
      completion = settled().then(() => {
        if (state === 'recording' && acknowledged === records.length) state = 'complete';
        return state;
      });
      return completion;
    }
  });
}

module.exports = {
  CASES,
  KINDS,
  OUTCOMES,
  TERMINAL_REASONS,
  DIAGNOSTICS,
  validateRecord,
  createReporter
};
