import type { ExpoConfig } from "expo/config";

const LOCAL_API_URL = "http://127.0.0.1:8000/hv/";
// A phone on the same wifi cannot reach 127.0.0.1; it has to dial the development
// machine's LAN address, which is exactly what `LAN_IP=... expo start --go` passes.
// A fixed list of loopback names made that flow impossible, so this matches every
// address range that is UNROUTABLE ON THE PUBLIC INTERNET -- which is the property
// that actually matters here: a password must never cross a network a stranger can
// join. Anything routable still owes https, opt-in or not.
// IPv6 patterns require the bracket the WHATWG URL parser always adds, so a public
// hostname beginning "fc" or "fe80" cannot slip through.
const PRIVATE_HOST = new RegExp(
  [
    "^localhost$",
    "\\.local$", // mDNS, e.g. macbook.local
    "^127\\.", // loopback
    "^10\\.", // RFC 1918, includes the Android emulator's 10.0.2.2
    "^192\\.168\\.", // RFC 1918
    "^172\\.(1[6-9]|2[0-9]|3[01])\\.", // RFC 1918, 172.16/12 only
    "^169\\.254\\.", // link-local
    "^\\[::1\\]$", // IPv6 loopback
    "^\\[f[cd][0-9a-f]*:", // IPv6 unique-local, fc00::/7
    "^\\[fe80:", // IPv6 link-local
  ].join("|"),
  "i",
);
// Expo's own CLI reads EAS_BUILD with getenv.boolish
// (@expo/cli/build/src/utils/env.js), so "1" is as true as "true". A stricter
// compare here would just fail open on a value the ecosystem accepts.
const BOOLISH_TRUE = /^(1|true)$/i;

/**
 * Resolves the API URL baked into the binary. Expo evaluates this config during
 * `expo config`, `expo prebuild` and again in the native build (expo-constants
 * writes extra.apiUrl into EXConstants.bundle), so throwing here fails the build
 * instead of shipping an app that talks to a machine nobody can reach.
 *
 * It fails CLOSED: cleartext and localhost are a deliberate developer opt-in, never
 * a default. Detecting "is this a release" is not reliable enough to hang store
 * safety on -- `expo prebuild` followed by an Xcode Archive sets no EAS variable at
 * all, and that native build phase re-resolves this very file.
 */
export function resolveApiUrl(env: Record<string, string | undefined> = process.env): string {
  const optedIn = BOOLISH_TRUE.test(env.EXPO_PUBLIC_ALLOW_LOCAL_API ?? "");
  const easRelease =
    BOOLISH_TRUE.test(env.EAS_BUILD ?? "") && env.EAS_BUILD_PROFILE !== "development";
  // The escape hatch is for development only: an opt-in that leaked into an EAS
  // release environment must not re-enable cleartext.
  const allowLocal = optedIn && !easRelease;
  const apiUrl = env.EXPO_PUBLIC_API_URL || (allowLocal ? LOCAL_API_URL : "");
  if (!apiUrl) {
    throw new Error(
      "EXPO_PUBLIC_API_URL is not set. There is no localhost default on purpose: " +
        "falling back to it would ship a binary that reaches nothing and gets " +
        "rejected under App Store guideline 2.1. Set it as an EAS environment " +
        "variable of type PLAIN TEXT or SENSITIVE -- secret-type variables are not " +
        `readable while the app config is resolved. For local development, set ` +
        `EXPO_PUBLIC_ALLOW_LOCAL_API=1 to use ${LOCAL_API_URL} (see mobile/.env.example).`
    );
  }
  const { protocol, hostname } = new URL(apiUrl);
  if (protocol !== "https:" && !(allowLocal && PRIVATE_HOST.test(hostname))) {
    throw new Error(
      `EXPO_PUBLIC_API_URL must use https (got "${apiUrl}"). ` +
        "This app posts a password on every login. Cleartext is only accepted for a " +
        "host that is unroutable from the public internet (localhost, a .local name, " +
        "or a private LAN address such as 192.168.x.x, 10.x.x.x or 172.16-31.x.x), " +
        "only with EXPO_PUBLIC_ALLOW_LOCAL_API=1, and never on an EAS build profile " +
        "other than development."
    );
  }
  return apiUrl;
}

export default (): ExpoConfig => {
  const apiUrl = resolveApiUrl();
  // One source of truth: the scheme of the URL we are actually shipping decides
  // whether the binary is allowed to speak cleartext, on both platforms.
  const allowCleartext = new URL(apiUrl).protocol !== "https:";

  return {
    name: "HyperTodo",
    slug: "hypertodo",
    version: "1.2.0",
    orientation: "portrait",
    icon: "./assets/icon.png",
    userInterfaceStyle: "light",
    scheme: "hypertodo",
    plugins: [
      // Omitting the plugin leaves android:usesCleartextTraffic unwritten, and
      // Android blocks cleartext by default at targetSdk >= 28.
      ...(allowCleartext
        ? [["expo-build-properties", { android: { usesCleartextTraffic: true } }] as [string, unknown]]
        : []),
      // cameraPermission and microphonePermission are literal `false`, not omitted:
      // the plugin writes ITS OWN default English strings for anything left
      // undefined, and only `false` both omits the iOS key and blocks the matching
      // Android permission. This app picks from the library and nothing else.
      [
        "expo-image-picker",
        {
          photosPermission: "HyperTodo uses your photo library so you can choose a profile picture.",
          cameraPermission: false,
          microphonePermission: false
        }
      ],
      ["expo-local-authentication", { faceIDPermission: "Sign in to HyperTodo with Face ID instead of typing your password." }],
      ["expo-secure-store", { faceIDPermission: "Sign in to HyperTodo with Face ID instead of typing your password." }],
      [
        "expo-splash-screen",
        {
          backgroundColor: "#F7F8FC",
          image: "./assets/splash-icon.png",
          imageWidth: 180
        }
      ]
    ],
    ios: {
      // Portrait-only, phone-shaped design: claiming iPad support buys an iPad
      // review surface and mandatory iPad screenshots. Flip it on deliberately.
      supportsTablet: false,
      bundleIdentifier: "com.eamigo.hypertodo",
      // withIosBaseMods merges ios.infoPlist shallowly over the Expo bare template's
      // plist, so this whole dict replaces the template's own NSAppTransportSecurity.
      // A top-level NSAllowsLocalNetworking key is inert - it must be nested here.
      infoPlist: {
        NSAppTransportSecurity: { NSAllowsArbitraryLoads: false, NSAllowsLocalNetworking: allowCleartext }
      }
    },
    android: {
      package: "com.eamigo.hypertodo",
      // Declared by the Expo bare template under "REMOVE WHATEVER YOU DO NOT NEED";
      // SYSTEM_ALERT_WINDOW in particular shows on the Play listing.
      blockedPermissions: [
        "android.permission.SYSTEM_ALERT_WINDOW",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE"
      ],
      adaptiveIcon: {
        backgroundColor: "#F7F8FC",
        foregroundImage: "./assets/android-icon-foreground.png",
        monochromeImage: "./assets/android-icon-monochrome.png"
      }
    },
    extra: { apiUrl }
  };
};
