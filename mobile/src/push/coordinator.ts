type Identity = Readonly<{authenticated: boolean; binding: string; generation: number}>;
type State = Readonly<{identity: Identity | null; availability: string; rootReady: boolean; generation: number}>;

export type PushRegistration = Readonly<{binding: string; expoToken: string; registrationVersion: string}>;
export type PushPorts = {
  supported(): Promise<boolean>;
  permission(): Promise<boolean>;
  getToken(deviceToken?: unknown): Promise<string | null>;
  onToken(callback: (deviceToken: unknown) => void): () => void;
  onTap(callback: (response: unknown) => void): () => void;
  lastTap(): Promise<unknown>;
  readInstallation(): Promise<string | null>;
  saveInstallation(value: string): Promise<void>;
  readRegistration(): Promise<PushRegistration | null>;
  saveRegistration(value: PushRegistration): Promise<void>;
  newInstallationId(): string;
};
export type PushSession = {
  snapshot(): State;
  subscribe(listener: () => void): () => void;
  request(path: string, init?: RequestInit): Promise<Response>;
  captureResources(): ((names: readonly "tasks"[]) => boolean) | null;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const TOKEN = /^(Expo|Exponent)PushToken\[[A-Za-z0-9_-]{1,220}\]$/;
const PATH = "/hv/push-registrations/";

function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

/** Registration belongs to a confirmed session; async native work never grants authority. */
export function createPushCoordinator(session: PushSession, ports: PushPorts) {
  let disposed = false;
  let started = false;
  let owner: Identity | null = null;
  let registered: PushRegistration | null = null;
  let pendingTap: {id: string; registrationVersion: string} | null = null;
  let seenTap: string | null = null;
  let running: Promise<void> | null = null;
  let runningOwner: Identity | null = null;
  let rerunForNewOwner = false;
  let pendingDeviceToken: unknown;
  let lastAvailability = session.snapshot().availability;
  let stopSession = () => {};
  let stopToken = () => {};
  let stopTap = () => {};

  const current = (identity: Identity) => {
    const state = session.snapshot();
    return !disposed && state.identity === identity && state.generation === identity.generation
      && identity.authenticated && state.availability === "foreground";
  };
  const readJson = async (response: Response, identity: Identity) => {
    const text = await response.text();
    if (!current(identity) || text.length > 2048) return null;
    try { return object(JSON.parse(text)); } catch { return null; }
  };
  const deliverTap = () => {
    if (!pendingTap || !registered || !owner || !current(owner)) return;
    if (pendingTap.registrationVersion !== registered.registrationVersion) {
      pendingTap = null;
      return;
    }
    const receiver = session.captureResources();
    if (receiver) {
      const candidate = pendingTap;
      pendingTap = null;
      receiver(["tasks"]);
      seenTap = candidate.id;
    }
  };
  const acceptTap = (value: unknown) => {
    const response = object(value), data = object(response?.data);
    if (!response || !data || Object.keys(data).sort().join(",") !== "kind,registrationVersion"
      || data.kind !== "tasks" || typeof response.id !== "string" || response.id.length > 128
      || !UUID.test(String(data.registrationVersion)) || response.id === seenTap) return;
    pendingTap = {id: response.id, registrationVersion: String(data.registrationVersion)};
    deliverTap();
  };
  const register = async (identity: Identity, deviceToken?: unknown) => {
    try {
      if (!await ports.supported() || !current(identity)) return;
      if (!await ports.permission() || !current(identity)) return;
      const expoToken = await ports.getToken(deviceToken);
      if (!current(identity) || !expoToken || !TOKEN.test(expoToken)) return;
      let installationId = await ports.readInstallation();
      if (!current(identity)) return;
      if (!installationId || !UUID.test(installationId)) {
        installationId = ports.newInstallationId();
        if (!UUID.test(installationId)) return;
        await ports.saveInstallation(installationId);
        if (!current(identity)) return;
      }
      const cached = await ports.readRegistration();
      if (!current(identity)) return;
      const get = await session.request(`${PATH}?installationId=${installationId}`, {headers: {Accept: "application/json"}});
      if (!current(identity) || get.status !== 200) return;
      const bootstrap = await readJson(get, identity);
      if (!bootstrap || typeof bootstrap.csrfToken !== "string" || !/^[a-zA-Z0-9]{32,128}$/.test(bootstrap.csrfToken)
        || (bootstrap.registrationVersion !== null && !UUID.test(String(bootstrap.registrationVersion)))) return;
      const serverVersion = bootstrap.registrationVersion as string | null;
      if (cached?.binding === identity.binding && cached.expoToken === expoToken
        && cached.registrationVersion === serverVersion) {
        registered = cached;
        deliverTap();
        return;
      }
      const body: Record<string, string> = {installationId, expoPushToken: expoToken};
      if (serverVersion) body.registrationVersion = serverVersion;
      const post = await session.request(PATH, {
        method: "POST", headers: {Accept: "application/json", "Content-Type": "application/json", "X-CSRFToken": bootstrap.csrfToken},
        body: JSON.stringify(body),
      });
      if (!current(identity) || ![200, 201].includes(post.status)) return;
      const result = await readJson(post, identity);
      if (!result || result.registered !== true || !UUID.test(String(result.registrationVersion))) return;
      const record = {binding: identity.binding, expoToken, registrationVersion: String(result.registrationVersion)};
      if (!current(identity)) return;
      await ports.saveRegistration(record);
      if (!current(identity)) return;
      registered = record;
      deliverTap();
    } catch {
      // Push is optional; authentication and Tasks remain available on native/network failure.
    }
  };
  const schedule = (deviceToken?: unknown) => {
    const state = session.snapshot(), identity = state.identity;
    if (!identity?.authenticated || state.availability !== "foreground" || disposed) return Promise.resolve();
    if (owner !== identity) {
      const previous = owner;
      owner = identity;
      registered = null;
      if (previous) pendingTap = null;
      seenTap = null;
      stopToken();
      stopToken = ports.onToken(nativeToken => {
        if (current(identity)) void schedule(nativeToken);
      });
    }
    if (running) {
      if (runningOwner !== identity) rerunForNewOwner = true;
      else pendingDeviceToken = deviceToken;
      return running;
    }
    runningOwner = identity;
    running = register(identity, deviceToken).finally(() => {
      running = null;
      runningOwner = null;
      if (rerunForNewOwner) {
        rerunForNewOwner = false;
        pendingDeviceToken = undefined;
        void schedule();
      } else if (pendingDeviceToken !== undefined) {
        const next = pendingDeviceToken;
        pendingDeviceToken = undefined;
        void schedule(next);
      }
    });
    return running;
  };
  return {
    async start() {
      if (started || disposed) return;
      started = true;
      stopSession = session.subscribe(() => {
        const state = session.snapshot();
        const resumed = lastAvailability !== "foreground" && state.availability === "foreground";
        lastAvailability = state.availability;
        if ((state.identity !== owner && state.identity?.authenticated) || resumed) void schedule();
        else deliverTap();
      });
      stopTap = ports.onTap(acceptTap);
      const last = await ports.lastTap().catch(() => null);
      if (disposed) return;
      acceptTap(last);
      await schedule();
    },
    dispose() {
      disposed = true;
      pendingTap = null;
      stopSession(); stopToken(); stopTap();
    },
  };
}
