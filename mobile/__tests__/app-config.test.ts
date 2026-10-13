import appConfig from "../app.config";

const LOCAL_URL = "http://127.0.0.1:8000/hv/";

/**
 * Calls the dynamic app config with a patched process.env and always restores it.
 * Keys set to undefined are deleted: jest-expo loads .env files, so a developer's
 * own EXPO_PUBLIC_API_URL would otherwise decide whether the fallback cases pass.
 */
function resolve(env: Record<string, string | undefined>) {
  const saved = { ...process.env };
  try {
    for (const [key, value] of Object.entries(env)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    return appConfig();
  } finally {
    for (const key of Object.keys(process.env)) delete process.env[key];
    Object.assign(process.env, saved);
  }
}

// Every key any case cares about, always explicit: jest-expo loads .env files, so
// a developer's own shell must never decide which branch a test takes.
const NO_EAS = {
  EXPO_PUBLIC_API_URL: undefined,
  EXPO_PUBLIC_ALLOW_LOCAL_API: undefined,
  EAS_BUILD: undefined,
  EAS_BUILD_PROFILE: undefined,
};
// The documented development shell (mobile/.env.example).
const DEV = { ...NO_EAS, EXPO_PUBLIC_ALLOW_LOCAL_API: "1" };
// The one configuration that ever produces a store binary.
const PROD_EAS = { ...NO_EAS, EAS_BUILD: "true", EAS_BUILD_PROFILE: "production" };

describe("app.config API URL guard", () => {
  it("uses the local URL when a developer opts in explicitly", () => {
    expect(resolve(DEV).extra!.apiUrl).toBe(LOCAL_URL);
  });

  it("refuses to resolve at all with no URL and no opt-in", () => {
    // `expo prebuild` + Xcode Archive sets no EAS variable, and expo-constants
    // re-resolves this config inside the native build phase, so a silent
    // localhost default there is a signed binary that reaches nothing.
    expect(() => resolve(NO_EAS)).toThrow(/EXPO_PUBLIC_API_URL/);
  });

  it("fails the build when the production profile has no API URL", () => {
    expect(() => resolve(PROD_EAS)).toThrow(/EXPO_PUBLIC_API_URL/);
  });

  it("explains that secret-type EAS variables are unreadable at config resolution", () => {
    expect(() => resolve(PROD_EAS)).toThrow(/secret/i);
  });

  it("still allows the local URL on the development EAS profile", () => {
    expect(
      resolve({ ...DEV, EAS_BUILD: "true", EAS_BUILD_PROFILE: "development" }).extra!.apiUrl,
    ).toBe(LOCAL_URL);
  });

  it.each(["true", "TRUE", "1"])(
    "rejects a local URL on a release profile, whatever EAS_BUILD=%s looks like",
    (easBuild) => {
      // Expo's own CLI reads EAS_BUILD with getenv.boolish, so "1" is as true as
      // "true"; a strict === "true" compare would fail open and ship localhost.
      expect(() =>
        resolve({
          ...PROD_EAS,
          EAS_BUILD: easBuild,
          EXPO_PUBLIC_API_URL: "http://10.0.2.2:8000/hv/",
        }),
      ).toThrow(/https/);
    },
  );

  it("ignores the dev opt-in on a release profile", () => {
    // .env.example carries a local URL. Pasting it into the EAS production
    // environment must not produce a cleartext binary, opt-in or not.
    expect(() =>
      resolve({
        ...PROD_EAS,
        EXPO_PUBLIC_ALLOW_LOCAL_API: "1",
        EXPO_PUBLIC_API_URL: "http://10.0.2.2:8000/hv/",
      }),
    ).toThrow(/https/);
  });

  // A phone on the same wifi cannot reach 127.0.0.1; it must dial the machine's LAN
  // address. Refusing those made `LAN_IP=... expo start --go` impossible, which is the
  // project's primary way of testing on a real device.
  it.each([
    ["a LAN address", "http://192.168.4.43:8000/hv/"],
    ["a 10/8 address", "http://10.1.2.3:8000/hv/"],
    ["a 172.16/12 address", "http://172.16.0.5:8000/hv/"],
    ["the top of 172.16/12", "http://172.31.255.254:8000/hv/"],
    ["a link-local address", "http://169.254.7.7:8000/hv/"],
    ["an mDNS name", "http://macbook.local:8000/hv/"],
    ["an IPv6 unique-local address", "http://[fd00::1]:8000/hv/"],
    ["localhost", "http://localhost:8000/hv/"],
    ["IPv4 loopback", "http://127.0.0.1:8000/hv/"],
    ["the Android emulator host alias", "http://10.0.2.2:8000/hv/"],
    ["IPv6 loopback", "http://[::1]:8000/hv/"],
    ["an IPv6 link-local address", "http://[fe80::1]:8000/hv/"],
  ])("accepts %s over cleartext for an opted-in developer", (_label, url) => {
    expect(resolve({ ...DEV, EXPO_PUBLIC_API_URL: url }).extra!.apiUrl).toBe(url);
  });

  // The whole point of the guard: unroutable is not the same as private-looking.
  it.each([
    ["just below 172.16/12", "http://172.15.0.1:8000/hv/"],
    ["just above 172.16/12", "http://172.32.0.1:8000/hv/"],
    ["a public address", "http://8.8.8.8:8000/hv/"],
    ["a public hostname", "http://api.example.com/hv/"],
    // Prefix matching treated these as private; each one is an ordinary public name.
    ["a public name starting with 10.", "http://10.example.com/hv/"],
    ["a public name starting with a loopback quad", "http://127.0.0.1.attacker.example/hv/"],
    ["a public name starting with a LAN quad", "http://192.168.1.1.evil.example/hv/"],
    ["a public name starting with a 172.16/12 pair", "http://172.16.evil.example/hv/"],
    ["a public name starting with a link-local pair", "http://169.254.attacker.example/hv/"],
  ])("still refuses %s over cleartext", (_label, url) => {
    expect(() => resolve({ ...DEV, EXPO_PUBLIC_API_URL: url })).toThrow(/must use https/);
  });

  it("refuses a LAN address without the explicit opt-in", () => {
    expect(() =>
      resolve({ ...NO_EAS, EXPO_PUBLIC_API_URL: "http://192.168.4.43:8000/hv/" }),
    ).toThrow(/must use https/);
  });

  it("refuses a LAN address on a release build profile even with the opt-in", () => {
    expect(() =>
      resolve({
        ...PROD_EAS,
        EXPO_PUBLIC_ALLOW_LOCAL_API: "1",
        EXPO_PUBLIC_API_URL: "http://192.168.4.43:8000/hv/",
      }),
    ).toThrow(/must use https/);
  });

  it("rejects a remote cleartext API URL even for a developer", () => {
    expect(() =>
      resolve({ ...DEV, EXPO_PUBLIC_API_URL: "http://api.example.com/hv/" }),
    ).toThrow(/https/);
  });

  it("accepts a remote https API URL", () => {
    expect(resolve({ ...NO_EAS, EXPO_PUBLIC_API_URL: "https://api.example.com/hv/" }).extra!.apiUrl).toBe(
      "https://api.example.com/hv/",
    );
  });

  // The runtime hard-codes root-level "/hv/..." request paths (session.ts,
  // session-protocol.ts, event-stream.ts), so a URL under any other path would pass
  // the build and then load nothing.
  it.each([
    ["a nested prefix", "https://api.example.com/api/hv/"],
    ["the bare origin with a slash", "https://api.example.com/"],
    ["the bare origin", "https://api.example.com"],
    ["a deeper path", "https://api.example.com/hv/tasks/"],
    ["a different case", "https://api.example.com/HV/"],
    ["a doubled slash", "https://api.example.com/hv//"],
    ["an unrelated path", "https://api.example.com/v1/"],
  ])("refuses %s as the API URL path", (_label, url) => {
    expect(() => resolve({ ...NO_EAS, EXPO_PUBLIC_API_URL: url })).toThrow(/must point at the "\/hv\/" path/);
  });

  it("applies the path rule to an opted-in developer URL as well", () => {
    expect(() =>
      resolve({ ...DEV, EXPO_PUBLIC_API_URL: "http://192.168.4.43:8000/api/" }),
    ).toThrow(/must point at the "\/hv\/" path/);
  });

  it("accepts the /hv path without its trailing slash, which the runtime normalizes", () => {
    expect(resolve({ ...NO_EAS, EXPO_PUBLIC_API_URL: "https://api.example.com/hv" }).extra!.apiUrl).toBe(
      "https://api.example.com/hv",
    );
  });

  // The guard judges the parsed URL, so what ships must be that parsed URL: returning the
  // raw string baked forms such as an upper-case host or a dot segment into the binary.
  it.each([
    ["an upper-case scheme and host", "HTTPS://API.Example.COM/hv/", "https://api.example.com/hv/"],
    ["an explicit default port", "https://api.example.com:443/hv/", "https://api.example.com/hv/"],
    ["a non-default port", "https://api.example.com:8443/hv/", "https://api.example.com:8443/hv/"],
    ["a dot segment", "https://api.example.com/./hv/", "https://api.example.com/hv/"],
    ["a parent segment", "https://api.example.com/api/../hv/", "https://api.example.com/hv/"],
    ["surrounding whitespace", "  https://api.example.com/hv/ ", "https://api.example.com/hv/"],
  ])("bakes the canonical form of %s into the binary", (_label, url, canonical) => {
    expect(resolve({ ...NO_EAS, EXPO_PUBLIC_API_URL: url }).extra!.apiUrl).toBe(canonical);
  });

  it("canonicalizes an opted-in developer URL the same way", () => {
    expect(resolve({ ...DEV, EXPO_PUBLIC_API_URL: "HTTP://LocalHost:80/hv/" }).extra!.apiUrl).toBe(
      "http://localhost/hv/",
    );
  });

  // The runtime refuses a URL with userinfo or a fragment (session.ts address()), so the
  // build refuses it first instead of shipping an app that cannot load anything.
  it.each([
    ["a username and password", "https://admin:s3cret@api.example.com/hv/"],
    ["only a username", "https://admin@api.example.com/hv/"],
    ["an empty password", "https://admin:@api.example.com/hv/"],
  ])("refuses %s in the API URL without echoing the secret", (_label, url) => {
    expect(() => resolve({ ...NO_EAS, EXPO_PUBLIC_API_URL: url })).toThrow(/must not contain credentials/);
    let message = "";
    try {
      resolve({ ...NO_EAS, EXPO_PUBLIC_API_URL: url });
    } catch (error) {
      message = (error as Error).message;
    }
    expect(message).not.toContain("s3cret");
    expect(message).not.toContain("admin");
  });

  it.each([
    ["a query", "https://api.example.com/hv/?next=/tasks/"],
    ["an empty query", "https://api.example.com/hv/?"],
    ["a fragment", "https://api.example.com/hv/#top"],
    ["an empty fragment", "https://api.example.com/hv/#"],
    ["a query and a fragment", "https://api.example.com/hv/?a=1#top"],
  ])("refuses %s in the API URL", (_label, url) => {
    expect(() => resolve({ ...NO_EAS, EXPO_PUBLIC_API_URL: url })).toThrow(/must not contain a query or a fragment/);
  });

  it("applies the credential, query and fragment rules to an opted-in developer URL as well", () => {
    expect(() => resolve({ ...DEV, EXPO_PUBLIC_API_URL: "http://dev:pw@192.168.4.43:8000/hv/" })).toThrow(
      /must not contain credentials/,
    );
    expect(() => resolve({ ...DEV, EXPO_PUBLIC_API_URL: "http://192.168.4.43:8000/hv/?x=1" })).toThrow(
      /query or a fragment/,
    );
    expect(() => resolve({ ...DEV, EXPO_PUBLIC_API_URL: "http://192.168.4.43:8000/hv/#x" })).toThrow(
      /query or a fragment/,
    );
  });

  // `ftp://localhost/` and `ws://localhost/` have a private host, so the opt-in used to
  // wave them through; the app only speaks http and https.
  it.each([
    "ftp://localhost:8000/hv/",
    "ws://localhost:8000/hv/",
    "wss://api.example.com/hv/",
    "custom://localhost/hv/",
    "file:///hv/",
    "javascript:alert(1)",
  ])("refuses the scheme of %s, opt-in or not", (url) => {
    expect(() => resolve({ ...DEV, EXPO_PUBLIC_API_URL: url })).toThrow(/must be an http or https URL/);
    expect(() => resolve({ ...NO_EAS, EXPO_PUBLIC_API_URL: url })).toThrow(/must be an http or https URL/);
  });
});

const REMOTE = { ...PROD_EAS, EXPO_PUBLIC_API_URL: "https://api.example.com/hv/" };

function buildProperties(config: ReturnType<typeof appConfig>) {
  return config.plugins!.find((plugin) => Array.isArray(plugin) && plugin[0] === "expo-build-properties");
}

describe("app.config cleartext and ATS gating", () => {
  it("enables Android cleartext only for a local API URL", () => {
    expect(buildProperties(resolve(DEV))).toEqual([
      "expo-build-properties",
      { android: { usesCleartextTraffic: true } }
    ]);
    expect(buildProperties(resolve(REMOTE))).toBeUndefined();
  });

  it("keeps the other config plugins when the cleartext one is dropped", () => {
    const names = resolve(REMOTE).plugins!.map((plugin) => (Array.isArray(plugin) ? plugin[0] : plugin));
    expect(names).toEqual([
      "expo-image-picker",
      "expo-local-authentication",
      "expo-secure-store",
      "expo-splash-screen"
    ]);
  });

  it("asks for the photo library and refuses the camera and microphone outright", () => {
    // Passing false rather than omitting is the point. The plugin's own source
    // (node_modules/expo-image-picker/plugin/build/withImagePicker.js) writes its
    // DEFAULT English strings for any key left undefined, and only a literal false
    // both omits the iOS key and BLOCKS the matching Android permission. This app
    // never opens a camera and never records audio.
    const plugin = resolve(REMOTE).plugins!.find(
      (entry) => Array.isArray(entry) && entry[0] === "expo-image-picker",
    ) as [string, Record<string, unknown>];

    expect(plugin[1].photosPermission).toEqual(expect.stringContaining("HyperTodo"));
    expect(plugin[1].cameraPermission).toBe(false);
    expect(plugin[1].microphonePermission).toBe(false);
  });

  it("ships the version the server gates the pick-avatar action on", () => {
    // Not cosmetic: todo/views.py MIN_AVATAR_UPLOAD_VERSION reads this exact
    // string off X-App-Version to decide whether to render a control this binary
    // can actually handle. Ship the feature without the bump and nobody sees it.
    expect(resolve(REMOTE).version).toBe("1.2.1");
  });

  it("leaves the photo permission keys to the plugin instead of hand-writing them", () => {
    expect(Object.keys(resolve(REMOTE).ios!.infoPlist!)).toEqual([
      "NSAppTransportSecurity"
    ]);
  });

  it("writes the nested ATS dict that actually overrides the Expo template", () => {
    expect(resolve(REMOTE).ios!.infoPlist!.NSAppTransportSecurity).toEqual({
      NSAllowsArbitraryLoads: false,
      NSAllowsLocalNetworking: false
    });
    expect(resolve(DEV).ios!.infoPlist!.NSAppTransportSecurity).toEqual({
      NSAllowsArbitraryLoads: false,
      NSAllowsLocalNetworking: true
    });
  });

  it("never reintroduces the inert top-level NSAllowsLocalNetworking key", () => {
    expect(resolve(DEV).ios!.infoPlist).not.toHaveProperty("NSAllowsLocalNetworking");
    expect(resolve(REMOTE).ios!.infoPlist).not.toHaveProperty("NSAllowsLocalNetworking");
  });

  it("does not claim iPad support for a portrait-only phone layout", () => {
    // supportsTablet: true commits the submission to iPad review and iPad
    // screenshots. Flipping it back on later is a normal app update.
    expect(resolve(REMOTE).ios!.supportsTablet).toBe(false);
  });

  it("blocks the unused Android permissions shipped by the Expo template", () => {
    // Deliberately UNCHANGED by the avatar work, and asserted so it stays that way.
    // expo-image-picker declares READ_EXTERNAL_STORAGE / WRITE_EXTERNAL_STORAGE at
    // maxSdkVersion=32, which this list strips at merge time -- and that is fine,
    // because launchImageLibraryAsync never requests them: the library path builds
    // an ActivityResultContracts.PickVisualMedia intent (the system Photo Picker),
    // and its own permission helper returns an EMPTY array on API 33+. Anyone who
    // "fixes" a picker bug by deleting an entry here fails this test instead.
    expect(resolve(REMOTE).android!.blockedPermissions).toEqual([
      "android.permission.SYSTEM_ALERT_WINDOW",
      "android.permission.READ_EXTERNAL_STORAGE",
      "android.permission.WRITE_EXTERNAL_STORAGE"
    ]);
  });
});
