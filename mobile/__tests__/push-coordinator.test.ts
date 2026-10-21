import {createPushCoordinator, type PushPorts, type PushRegistration} from "../src/push/coordinator";

const A = "hvs1." + "A".repeat(43);
const B = "hvs1." + "B".repeat(43);
const INSTALLATION = "11111111-1111-4111-8111-111111111111";
const FIRST = "22222222-2222-4222-8222-222222222222";
const SECOND = "33333333-3333-4333-8333-333333333333";
const TOKEN = "ExpoPushToken[first]";

function reply(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {status});
}

function fixture() {
  let identity: {authenticated: boolean; binding: string; generation: number} | null =
    {authenticated: true, binding: A, generation: 1};
  let availability = "foreground", rootReady = true;
  let serverVersion: string | null = null;
  let installation: string | null = null;
  let registration: PushRegistration | null = null;
  let token = TOKEN;
  let allowed = true;
  let supported = true;
  let tap: ((value: unknown) => void) | null = null;
  let tokenChange: ((value: unknown) => void) | null = null;
  const listeners = new Set<() => void>();
  const receive = jest.fn(() => true);
  const request = jest.fn(async (path: string, init?: RequestInit) => {
    if ((init?.method ?? "GET") === "GET") {
      return reply({csrfToken: "c".repeat(64), registrationVersion: serverVersion});
    }
    if (init?.method === "POST") {
      const payload = JSON.parse(String(init.body));
      serverVersion = payload.registrationVersion ? SECOND : FIRST;
      return reply({registered: true, registrationVersion: serverVersion}, payload.registrationVersion ? 200 : 201);
    }
    throw new Error("unexpected request");
  });
  const session = {
    snapshot: () => ({identity, availability, rootReady, generation: identity?.generation ?? 0}),
    subscribe: (listener: () => void) => {listeners.add(listener); return () => {listeners.delete(listener);};},
    request,
    captureResources: () => identity?.authenticated && rootReady && availability === "foreground" ? receive : null,
  };
  const ports: PushPorts = {
    supported: jest.fn(async () => supported),
    permission: jest.fn(async () => allowed),
    getToken: jest.fn(async (deviceToken?: unknown) => typeof deviceToken === "string" ? deviceToken : token),
    onToken: jest.fn(callback => {tokenChange = callback; return () => {tokenChange = null;};}),
    onTap: jest.fn(callback => {tap = callback; return () => {tap = null;};}),
    lastTap: jest.fn(async () => null),
    readInstallation: jest.fn(async () => installation),
    saveInstallation: jest.fn(async value => {installation = value;}),
    readRegistration: jest.fn(async () => registration),
    saveRegistration: jest.fn(async value => {registration = value;}),
    newInstallationId: jest.fn(() => INSTALLATION),
  };
  const notify = () => {for (const listener of listeners) listener();};
  return {
    session, ports, request, receive,
    get registration() {return registration;},
    set supported(value: boolean) {supported = value;},
    set allowed(value: boolean) {allowed = value;},
    set token(value: string) {token = value;},
    set rootReady(value: boolean) {rootReady = value; notify();},
    set availability(value: string) {availability = value; notify();},
    switchAccount() {identity = {authenticated: true, binding: B, generation: 2}; serverVersion = null; notify();},
    logout() {identity = {authenticated: false, binding: B, generation: 2}; notify();},
    emitToken(value: string) {tokenChange?.(value);},
    captureTokenCallback() {return tokenChange;},
    emitTap(value: unknown) {tap?.(value);},
    setLastTap(value: unknown) {(ports.lastTap as jest.Mock).mockResolvedValue(value);},
  };
}

const settle = async () => {
  for (let index = 0; index < 30; index++) await Promise.resolve();
};

test("registers only the authenticated foreground owner and preserves an unchanged revision", async () => {
  const f = fixture(), coordinator = createPushCoordinator(f.session, f.ports);
  await coordinator.start();
  expect(f.request).toHaveBeenCalledTimes(2);
  const [getPath] = f.request.mock.calls[0];
  expect(getPath).toBe(`/hv/push-registrations/?installationId=${INSTALLATION}`);
  const [, post] = f.request.mock.calls[1];
  expect(post?.method).toBe("POST");
  expect(new Headers(post?.headers).get("X-CSRFToken")).toBe("c".repeat(64));
  expect(JSON.parse(String(post?.body))).toEqual({installationId: INSTALLATION, expoPushToken: TOKEN});
  expect(f.registration).toEqual({binding: A, expoToken: TOKEN, registrationVersion: FIRST});
  f.availability = "paused";
  f.availability = "foreground";
  await settle();
  expect(f.request).toHaveBeenCalledTimes(3);
  expect(f.request.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  coordinator.dispose();
});

test("denied permission and unsupported Expo Go never touch the registration API", async () => {
  const denied = fixture(); denied.allowed = false;
  const first = createPushCoordinator(denied.session, denied.ports);
  await first.start();
  expect(denied.request).not.toHaveBeenCalled();
  denied.availability = "paused";
  denied.availability = "foreground";
  await settle();
  expect(denied.request).not.toHaveBeenCalled();
  first.dispose();
  const unsupported = fixture(); unsupported.supported = false;
  const second = createPushCoordinator(unsupported.session, unsupported.ports);
  await second.start();
  expect(unsupported.request).not.toHaveBeenCalled();
  expect(unsupported.ports.getToken).not.toHaveBeenCalled();
  second.dispose();
});

test("rotates only when the Expo token changes and does not adopt another account", async () => {
  const f = fixture(), coordinator = createPushCoordinator(f.session, f.ports);
  await coordinator.start();
  f.emitToken("ExpoPushToken[second]");
  await settle();
  expect(f.registration).toEqual({binding: A, expoToken: "ExpoPushToken[second]", registrationVersion: SECOND});
  f.switchAccount();
  f.emitToken("ExpoPushToken[late_a]");
  await settle();
  expect(f.registration?.binding).not.toBe(A);
  coordinator.dispose();
});

test("queues a cold-start tap until current registration and gate are ready, without using URLs", async () => {
  const f = fixture();
  f.rootReady = false;
  f.setLastTap({id: "tap-1", data: {kind: "tasks", registrationVersion: FIRST}});
  const coordinator = createPushCoordinator(f.session, f.ports);
  await coordinator.start();
  expect(f.receive).not.toHaveBeenCalled();
  f.rootReady = true;
  await settle();
  expect(f.receive).toHaveBeenCalledWith(["tasks"]);
  f.emitTap({id: "tap-2", data: {kind: "tasks", registrationVersion: FIRST, url: "https://evil.invalid"}});
  await settle();
  expect(f.receive).toHaveBeenCalledTimes(1);
  coordinator.dispose();
});

test("logout and stale-account taps never refresh a new owner's tasks", async () => {
  const f = fixture(), coordinator = createPushCoordinator(f.session, f.ports);
  await coordinator.start();
  f.logout();
  f.emitTap({id: "tap-old", data: {kind: "tasks", registrationVersion: FIRST}});
  await settle();
  expect(f.receive).not.toHaveBeenCalled();
  coordinator.dispose();
});

test("a late native token callback from a retired subscription cannot write the next owner", async () => {
  const f = fixture(), coordinator = createPushCoordinator(f.session, f.ports);
  await coordinator.start();
  const stale = f.captureTokenCallback();
  f.switchAccount();
  stale?.("ExpoPushToken[retired]");
  await settle();
  expect(f.registration?.binding).toBe(B);
  expect(f.registration?.expoToken).toBe(TOKEN);
  coordinator.dispose();
});

test("a malformed or cross-version tap never reaches the resource gate", async () => {
  const f = fixture(), coordinator = createPushCoordinator(f.session, f.ports);
  await coordinator.start();
  f.emitTap({id: "wrong", data: {kind: "tasks", registrationVersion: SECOND}});
  f.emitTap({id: "unknown", data: {kind: "task", registrationVersion: FIRST}});
  f.emitTap({id: "extra", data: {kind: "tasks", registrationVersion: FIRST, url: "https://evil.invalid"}});
  expect(f.receive).not.toHaveBeenCalled();
  coordinator.dispose();
});

test("a retired in-flight bootstrap cannot register A or suppress B's later registration", async () => {
  const f = fixture();
  let release!: () => void;
  const blocked = reply({csrfToken: "c".repeat(64), registrationVersion: null});
  blocked.text = () => new Promise<string>(resolve => {release = () => resolve(JSON.stringify({csrfToken: "c".repeat(64), registrationVersion: null}));});
  f.request.mockImplementationOnce(async () => blocked);
  const coordinator = createPushCoordinator(f.session, f.ports);
  const starting = coordinator.start();
  await settle();
  f.switchAccount();
  release();
  await starting; await settle();
  expect(f.registration?.binding).toBe(B);
  expect(f.request.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  coordinator.dispose();
});

test("malformed CSRF bootstrap, oversized JSON and refused POST fail closed", async () => {
  for (const response of [reply({csrfToken: "short", registrationVersion: null}),
    new Response("x".repeat(2049), {status: 200}), reply({}, 403)]) {
    const f = fixture();
    f.request.mockImplementationOnce(async () => response);
    const coordinator = createPushCoordinator(f.session, f.ports);
    await coordinator.start();
    expect(f.registration).toBeNull();
    expect(f.request).toHaveBeenCalledTimes(1);
    coordinator.dispose();
  }
  const f = fixture();
  f.request.mockImplementationOnce(async () => reply({csrfToken: "c".repeat(64), registrationVersion: null}))
    .mockImplementationOnce(async () => reply({registered: false}, 409));
  const coordinator = createPushCoordinator(f.session, f.ports);
  await coordinator.start();
  expect(f.registration).toBeNull();
  coordinator.dispose();
});

test("invalid installation ID and native storage failures never send credentials", async () => {
  const invalid = fixture();
  (invalid.ports.newInstallationId as jest.Mock).mockReturnValue("not-a-uuid");
  const first = createPushCoordinator(invalid.session, invalid.ports);
  await first.start();
  expect(invalid.request).not.toHaveBeenCalled();
  first.dispose();
  const failed = fixture();
  (failed.ports.readInstallation as jest.Mock).mockRejectedValue(new Error("keychain unavailable"));
  const second = createPushCoordinator(failed.session, failed.ports);
  await expect(second.start()).resolves.toBeUndefined();
  expect(failed.request).not.toHaveBeenCalled();
  second.dispose();
});

test("repeated start and disposed cold-start callback cannot resurrect a registration", async () => {
  const f = fixture(), coordinator = createPushCoordinator(f.session, f.ports);
  await coordinator.start();
  await coordinator.start();
  expect(f.request).toHaveBeenCalledTimes(2);
  coordinator.dispose();
  f.emitTap({id: "late", data: {kind: "tasks", registrationVersion: FIRST}});
  expect(f.receive).not.toHaveBeenCalled();
});

test("a native token rotated during backgrounding is reconciled on foreground return", async () => {
  const f = fixture(), coordinator = createPushCoordinator(f.session, f.ports);
  await coordinator.start();
  f.availability = "paused";
  f.token = "ExpoPushToken[resumed]";
  f.availability = "foreground";
  await settle();
  expect(f.registration).toEqual({binding: A, expoToken: "ExpoPushToken[resumed]", registrationVersion: SECOND});
  coordinator.dispose();
});
