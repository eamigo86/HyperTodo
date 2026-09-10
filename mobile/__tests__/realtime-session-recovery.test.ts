import { createSessionSupervisor, type RecoveryHandle } from '../src/realtime/session';
declare const __dirname: string; // Supplied by this Jest module, not the native App.
import { SESSION_HEADERS as H } from '../src/realtime/session-protocol';
const fs = jest.requireActual('fs');
const ORIGIN = 'https://app.test',
  A = 'hvs1.' + 'A'.repeat(43),
  B = 'hvs1.' + 'B'.repeat(43),
  C = 'hvs1.' + 'C'.repeat(43);
const login = fs.readFileSync(jest.requireActual("path").resolve(__dirname, "../../backend/hyperview/fragments/login_transition.xml"), 'utf8').replace('{{ biometric_token }}', 't'.repeat(43));
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => {
    resolve = yes;
  });
  return {
    promise,
    resolve
  };
}
function response(body: string, binding: string, outcome?: string, status = 200) {
  const r = new Response(body, {
    status,
    headers: {
      [H.binding]: binding,
      ...(outcome ? {
        [H.outcome]: outcome
      } : {}),
      'Content-Type': 'application/vnd.hyperview+xml',
      'X-HyperTodo-Theme': 'dark',
      'Content-Language': 'es'
    }
  });
  Object.defineProperty(r, 'url', {
    value: ORIGIN + '/hv/recovery/'
  });
  return r;
}
function setup() {
  let binding = A;
  const save = jest.fn(async () => {}),
    clear = jest.fn(async () => {}),
    theme = jest.fn(),
    language = jest.fn(),
    publish = jest.fn();
  const transport = jest.fn(async (url: string, init: RequestInit): Promise<Response> => {
    if (url.endsWith('/session-state/')) return response(JSON.stringify({
      version: 1,
      authenticated: true,
      binding
    }), binding);
    if (init.method === 'POST') {
      binding = C;
      return response(login, C, 'password-ok');
    }
    return response('<doc xmlns="https://hyperview.org/hyperview"><navigator id="root" type="stack"><nav-route id="login" href="/hv/recovery/?screen=login" selected="true"/></navigator></doc>', binding);
  });
  const supervisor = createSessionSupervisor({
    origin: ORIGIN,
    transport,
    storage: {
      enqueue: job => job({
        save,
        clear
      })
    },
    stopStream: () => {},
    onIdentity: publish,
    onTheme: theme,
    onLanguage: language
  });
  return {
    supervisor,
    transport,
    save,
    clear,
    theme,
    language,
    publish,
    setBinding: (value: string) => {
      binding = value;
    }
  };
}
async function recover(f: ReturnType<typeof setup>): Promise<RecoveryHandle> {
  await f.supervisor.bootstrap();
  f.supervisor.invalidate();
  f.setBinding(B);
  const result = await f.supervisor.beginRecovery();
  expect(result.kind).toBe('recovery');
  if (result.kind !== 'recovery') throw new Error('Expected recovery');
  return result.handle;
}
it('mints only explicit neutral capability without adopting observed B or publishing its metadata', async () => {
  const f = setup(),
    handle = await recover(f);
  expect(f.supervisor.snapshot().identity).toBeNull();
  expect(f.publish.mock.calls.filter(([identity]) => identity?.binding === B)).toHaveLength(0);
  const r = await handle.fetch(ORIGIN + '/hv/recovery/');
  expect(await r.text()).toContain('navigator');
  await handle.fetch(ORIGIN + '/hv/recovery/?screen=login');
  for (const [url, init] of f.transport.mock.calls.slice(1)) expect(new Headers(init.headers).get('X-HyperTodo-Recovery')).toBe('login-v1');
  expect(f.theme).not.toHaveBeenCalled();
  expect(f.language).not.toHaveBeenCalled();
  expect(f.supervisor.snapshot().rootReady).toBe(false);
});
it.each(['/hv/', '/hv/tasks/', '/hv/recovery/?screen=other', 'https://other.test/hv/recovery/'])('rejects recovery URL %s before transport', async url => {
  const f = setup(),
    handle = await recover(f),
    count = f.transport.mock.calls.length;
  await expect(handle.fetch(url)).rejects.toThrow();
  await expect(handle.fetch('/hv/recovery/', {
    method: 'POST'
  })).rejects.toThrow();
  expect(f.transport).toHaveBeenCalledTimes(count);
});
it('rejects a revoked handle and a cookie mismatch before reading content or admitting auth', async () => {
  const f = setup(),
    handle = await recover(f);
  const bad = response('private C', C);
  const text = jest.spyOn(bad, 'text');
  f.transport.mockResolvedValueOnce(bad);
  await expect(handle.fetch('/hv/recovery/')).rejects.toThrow();
  expect(text).not.toHaveBeenCalled();
  expect(handle.isAlive()).toBe(false);
  const count = f.transport.mock.calls.length;
  await expect(handle.authenticate('/hv/login/', {
    method: 'POST'
  })).resolves.toMatchObject({
    kind: 'stale'
  });
  expect(f.transport).toHaveBeenCalledTimes(count);
});
it('retains the POST settlement barrier after revoke and does not auto-replay auth', async () => {
  const f = setup();
  await f.supervisor.bootstrap();
  const hold = deferred<Response>();
  f.transport.mockImplementationOnce(() => hold.promise);
  const pending = f.supervisor.authenticate('/hv/login/', {
    method: 'POST'
  });
  await Promise.resolve();
  f.supervisor.invalidate();
  await expect(f.supervisor.beginRecovery()).resolves.toMatchObject({
    kind: 'busy'
  });
  expect(f.transport.mock.calls.filter(([, init]) => init.method === 'POST')).toHaveLength(1);
  hold.resolve(response(login, C, 'password-ok'));
  await pending;
  f.setBinding(B);
  await expect(f.supervisor.beginRecovery()).resolves.toMatchObject({
    kind: 'recovery'
  });
});
it('publishes only the successful auth binding C after one stored effect and final confirmation', async () => {
  const f = setup(),
    handle = await recover(f);
  await expect(handle.authenticate('/hv/logout/', {
    method: 'POST'
  })).resolves.toMatchObject({
    kind: 'stale'
  });
  const result = await handle.authenticate('/hv/login/', {
    method: 'POST',
    body: 'csrfmiddlewaretoken=real&username=C'
  });
  expect(result).toMatchObject({
    kind: 'transition',
    identity: {
      binding: C
    }
  });
  expect(f.save).toHaveBeenCalledTimes(1);
  expect(handle.isAlive()).toBe(false);
  expect(f.theme).not.toHaveBeenCalled();
  expect(f.supervisor.snapshot().identity?.binding).toBe(C);
});
it('pauses the public authority and confirms its same binding before resuming without adopting it', async () => {
  const f = setup(),
    handle = await recover(f);
  f.supervisor.pause();
  await expect(handle.fetch('/hv/recovery/')).rejects.toThrow();
  await f.supervisor.foreground();
  expect(handle.isCurrent()).toBe(true);
  expect(f.supervisor.snapshot().identity).toBeNull();
  f.supervisor.pause();
  f.setBinding(C);
  await f.supervisor.foreground();
  expect(handle.isAlive()).toBe(false);
  expect(f.supervisor.snapshot().identity).toBeNull();
});
it('requires an exact recovery auth path before transport', async () => {
  const f = setup(),
    handle = await recover(f);
  const count = f.transport.mock.calls.length;
  await expect(handle.authenticate('/hv/login/?next=private', {
    method: 'POST'
  })).resolves.toMatchObject({
    kind: 'stale'
  });
  expect(f.transport).toHaveBeenCalledTimes(count);
});
it('confirms a held401 panel before permitting the next recovery action', async () => {
  const f = setup(),
    handle = await recover(f);
  const body = deferred<string>();
  const panel = '<view xmlns="https://hyperview.org/hyperview" id="login-panel"><behavior trigger="load" action="store-biometric-token" token="" once="true" immediate="true"/></view>';
  const raw = response('', B, 'biometric-invalid', 401);
  jest.spyOn(raw, 'text').mockImplementation(() => body.promise);
  f.transport.mockResolvedValueOnce(raw);
  const pending = handle.authenticate('/hv/biometric/login/', {
    method: 'POST'
  });
  await Promise.resolve();
  await Promise.resolve();
  f.supervisor.pause();
  body.resolve(panel);
  await expect(pending).resolves.toMatchObject({
    kind: 'held'
  });
  expect(f.clear).not.toHaveBeenCalled();
  await expect(f.supervisor.foreground()).resolves.toMatchObject({
    kind: 'panel',
    status: 401
  });
  expect(f.clear).toHaveBeenCalledTimes(1);
  expect(handle.isCurrent()).toBe(true);
  await expect(handle.fetch('/hv/recovery/?screen=login')).resolves.toBeTruthy();
});
it('does not mint recovery while an admitted ordinary request or a real native write is unsettled, then progresses explicitly', async () => {
  const f = setup();
  await f.supervisor.bootstrap();
  const pending = deferred<Response>();
  f.transport.mockImplementationOnce(() => pending.promise);
  const request = f.supervisor.request('/hv/settings/', {
    method: 'POST',
    body: 'csrf=own'
  }).catch(() => {});
  await Promise.resolve();
  f.supervisor.invalidate();
  await expect(f.supervisor.beginRecovery()).resolves.toMatchObject({
    kind: 'busy'
  });
  pending.resolve(response('<view/>', A));
  await request;
  f.setBinding(B);
  const result = await f.supervisor.beginRecovery();
  expect(result.kind).toBe('recovery');
  const g = setup();
  await g.supervisor.bootstrap();
  const native = deferred<void>();
  g.clear.mockImplementationOnce(() => native.promise);
  const write = g.supervisor.lease(() => true).clearCredential({});
  await Promise.resolve();
  expect(g.clear).toHaveBeenCalledTimes(1);
  g.supervisor.invalidate();
  await expect(g.supervisor.beginRecovery()).resolves.toMatchObject({
    kind: 'busy'
  });
  native.resolve();
  await write;
  g.setBinding(B);
  await expect(g.supervisor.beginRecovery()).resolves.toMatchObject({
    kind: 'recovery'
  });
  expect(g.clear).toHaveBeenCalledTimes(1);
});
it('bounds neutral UTF-8 bodies and refuses late body delivery after revocation', async () => {
  const f = setup(),
    handle = await recover(f);
  f.transport.mockResolvedValueOnce(response('é'.repeat(131073), B));
  const large = await handle.fetch('/hv/recovery/');
  await expect(large.text()).rejects.toThrow('recovery-body-too-large');
  expect(handle.isAlive()).toBe(false);
  const g = setup(),
    second = await recover(g),
    body = deferred<string>();
  const raw = response('', B);
  jest.spyOn(raw, 'text').mockImplementation(() => body.promise);
  g.transport.mockResolvedValueOnce(raw);
  const result = await second.fetch('/hv/recovery/');
  const reading = result.text();
  second.revoke();
  body.resolve('private late');
  await expect(reading).rejects.toThrow('stale-owner');
  expect(g.theme).not.toHaveBeenCalled();
  expect(g.language).not.toHaveBeenCalled();
});
it('can confirm the first foreground after a paused startup, but cannot bootstrap after explicit revocation', async () => {
  const f = setup();
  f.supervisor.pause();
  await expect(f.supervisor.bootstrap()).resolves.toBe('uncertain');
  await f.supervisor.foreground();
  expect(f.supervisor.snapshot().identity?.binding).toBe(A);
});
it('cannot bootstrap an unexpected cookie after explicit revocation before initial confirmation', async () => {
  const g = setup();
  g.supervisor.invalidate();
  g.setBinding(B);
  await g.supervisor.foreground();
  expect(g.supervisor.snapshot().identity).toBeNull();
  await expect(g.supervisor.bootstrap()).resolves.toBe('uncertain');
  expect(g.supervisor.snapshot().identity).toBeNull();
});
it('treats a binding-less recovery auth500 as uncertain and confirms state without replay or native effects', async () => {
  const f = setup(),
    handle = await recover(f);
  const failed = new Response('{"error":"recovery-render-failed"}', {
    status: 500,
    headers: {
      'Content-Type': 'application/json'
    }
  });
  Object.defineProperty(failed, 'url', {
    value: ORIGIN + '/hv/login/'
  });
  f.transport.mockResolvedValueOnce(failed);
  const before = f.transport.mock.calls.filter(([url]) => url.endsWith('/session-state/')).length;
  await expect(handle.authenticate('/hv/login/', {
    method: 'POST',
    body: 'username=own&csrfmiddlewaretoken=real'
  })).resolves.toMatchObject({
    kind: 'uncertain'
  });
  expect(f.transport.mock.calls.filter(([, init]) => init.method === 'POST')).toHaveLength(1);
  expect(f.transport.mock.calls.filter(([url]) => url.endsWith('/session-state/'))).toHaveLength(before + 1);
  expect(f.save).not.toHaveBeenCalled();
  expect(f.clear).not.toHaveBeenCalled();
  expect(f.supervisor.snapshot().identity).toBeNull();
  expect(f.supervisor.snapshot().availability).toBe('uncertain');
});
