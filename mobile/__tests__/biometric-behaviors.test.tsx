import { DOMParser } from "@instawork/xmldom";
import { Platform } from "react-native";
import * as LocalAuthentication from "expo-local-authentication";
import * as SecureStore from "expo-secure-store";
import * as Events from "hyperview/src/services/events";

import BiometricUnlockBehavior from "../src/behaviors/BiometricUnlockBehavior";
import ProbeBiometricsBehavior from "../src/behaviors/ProbeBiometricsBehavior";
import StoreBiometricTokenBehavior from "../src/behaviors/StoreBiometricTokenBehavior";
import {
  hasEnrolledBiometrics,
  preferredBiometricIcon,
  readToken,
  saveToken,
} from "../src/biometrics/store";
import { subscribeToSnackbars } from "../src/feedback/snackbar";
import { hyperviewLogger } from "../src/feedback/logging";
import type { SnackbarNotice } from "../src/feedback/snackbar";

jest.mock("expo-local-authentication", () => ({
  authenticateAsync: jest.fn(),
  hasHardwareAsync: jest.fn(),
  isEnrolledAsync: jest.fn(),
  supportedAuthenticationTypesAsync: jest.fn(),
  // The factory replaces the whole module, so the enum has to be restated or
  // AuthenticationType.FACIAL_RECOGNITION is undefined at import time.
  // Values from expo-local-authentication/src/LocalAuthentication.types.ts:16-25.
  AuthenticationType: { FINGERPRINT: 1, FACIAL_RECOGNITION: 2, IRIS: 3 },
}));

jest.mock("expo-secure-store", () => ({
  deleteItemAsync: jest.fn(),
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: "when-unlocked-this-device-only",
}));

const mockAuth = LocalAuthentication as jest.Mocked<typeof LocalAuthentication>;
const mockStore = SecureStore as jest.Mocked<typeof SecureStore>;

// The exact panel the backend ships, so the client tests break if either side drifts.
const PANEL = `<view xmlns="https://hyperview.org/hyperview" id="login-panel">
  <view id="biometric-optin" hide="true">
    <switch id="biometric-optin-switch" name="enable_biometrics" value="off" />
  </view>
  <form id="biometric-form">
    <text-field hide="true" id="biometric-token" name="biometric_token" value="" />
    <view id="biometric-signin" hide="true">
      <image hide="true" variant="face" source="/static/todo/icons/face-id.png" alt="Sign in with face recognition" />
      <image hide="true" variant="fingerprint" source="/static/todo/icons/fingerprint.png" alt="Sign in with your fingerprint" />
    </view>
  </form>
</view>`;

function panel(): Document {
  return new DOMParser().parseFromString(PANEL, "application/xml") as Document;
}

function behaviorElement(attributes: Record<string, string>): Element {
  return {
    getAttribute: (name: string) => attributes[name] ?? null,
  } as Element;
}

function hideOf(doc: Document, id: string): string | null {
  return (doc.getElementById(id) as Element | null)?.getAttribute("hide") ?? null;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockStore.setItemAsync.mockResolvedValue(undefined);
  mockStore.deleteItemAsync.mockResolvedValue(undefined);
  mockStore.getItemAsync.mockResolvedValue(null);
});

describe("behavior registration", () => {
  it("registers the three action names the backend HXML uses", () => {
    expect(StoreBiometricTokenBehavior.action).toBe("store-biometric-token");
    expect(ProbeBiometricsBehavior.action).toBe("probe-biometrics");
    expect(BiometricUnlockBehavior.action).toBe("biometric-unlock");
  });
});

describe("device credential store", () => {
  it("reports biometrics unavailable when the hardware is missing", async () => {
    mockAuth.hasHardwareAsync.mockResolvedValue(false);
    mockAuth.isEnrolledAsync.mockResolvedValue(true);

    await expect(hasEnrolledBiometrics()).resolves.toBe(false);
  });

  it("reports biometrics unavailable when nothing is enrolled", async () => {
    mockAuth.hasHardwareAsync.mockResolvedValue(true);
    mockAuth.isEnrolledAsync.mockResolvedValue(false);

    await expect(hasEnrolledBiometrics()).resolves.toBe(false);
  });

  it("reports biometrics available only with hardware and an enrolment", async () => {
    mockAuth.hasHardwareAsync.mockResolvedValue(true);
    mockAuth.isEnrolledAsync.mockResolvedValue(true);

    await expect(hasEnrolledBiometrics()).resolves.toBe(true);
  });

  it("keeps the device token out of an iCloud backup", async () => {
    // The default accessibility is WHEN_UNLOCKED, which migrates on restore, and the
    // server binds this token to a USER but never to a device: a restored backup is a
    // working credential on the restorer's phone.
    await saveToken("issued-token");

    expect(mockStore.setItemAsync).toHaveBeenCalledWith(
      expect.any(String),
      "issued-token",
      { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY },
    );
  });

  it("swallows keychain read failures instead of crashing the login screen", async () => {
    mockStore.getItemAsync.mockRejectedValue(new Error("keychain locked"));

    await expect(readToken()).resolves.toBeNull();
  });
});

describe("preferred biometric icon", () => {
  // jest.replaceProperty is only auto-restored by restoreAllMocks, and the global
  // beforeEach only clears. Without this, Platform.OS leaks into every later test.
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it.each([
    [[2], "face"],
    [[1], "fingerprint"],
    // Android reports HARDWARE presence, not enrolment
    // (LocalAuthenticationModule.kt:292), and only Android can report several. A
    // fingerprint glyph on a phone that prompts for face is a mild mismatch the
    // system prompt explains; a Face ID glyph with no face enrolled is the exact
    // confusion this change exists to remove.
    [[1, 2], "fingerprint"],
    [[3], "fingerprint"],
  ])("picks the glyph the device actually reports (%p)", async (types, expected) => {
    mockAuth.supportedAuthenticationTypesAsync.mockResolvedValue(types);

    await expect(preferredBiometricIcon()).resolves.toBe(expected);
  });

  // Empty happens for real: iOS Optic ID, which LocalAuthenticationModule.swift:26-38
  // never maps, and Android BIOMETRIC_ERROR_NO_HARDWARE or an OEM declaring none of
  // the four feature strings (kt:39-49). Platform is the only signal left.
  it.each([
    ["ios", "face"],
    ["android", "fingerprint"],
  ])("falls back to the platform default on %s when nothing is reported", async (os, expected) => {
    jest.replaceProperty(Platform, "OS", os as typeof Platform.OS);
    mockAuth.supportedAuthenticationTypesAsync.mockResolvedValue([]);

    await expect(preferredBiometricIcon()).resolves.toBe(expected);
  });

  it("falls back to the platform default when the native probe throws", async () => {
    jest.replaceProperty(Platform, "OS", "ios");
    mockAuth.supportedAuthenticationTypesAsync.mockRejectedValue(
      new Error("UnavailabilityError"),
    );

    await expect(preferredBiometricIcon()).resolves.toBe("face");
  });
});

describe("store-biometric-token", () => {
  it("stores the server-issued token under a single key", async () => {
    StoreBiometricTokenBehavior.callback(
      behaviorElement({ token: "issued-token" }),
      jest.fn(),
      jest.fn(),
      jest.fn(),
    );
    await Promise.resolve();

    expect(mockStore.setItemAsync).toHaveBeenCalledTimes(1);
    expect(mockStore.setItemAsync.mock.calls[0][1]).toBe("issued-token");
    expect(mockStore.deleteItemAsync).not.toHaveBeenCalled();
  });

  it.each([{ token: "" }, { token: "   " }, {}])(
    "clears the device when the server sends no token (%p)",
    async (attributes) => {
      StoreBiometricTokenBehavior.callback(
        behaviorElement(attributes as Record<string, string>),
        jest.fn(),
        jest.fn(),
        jest.fn(),
      );
      await Promise.resolve();

      expect(mockStore.deleteItemAsync).toHaveBeenCalledTimes(1);
      expect(mockStore.setItemAsync).not.toHaveBeenCalled();
    },
  );

  it("clears the device when the keystore refuses the write", async () => {
    mockStore.setItemAsync.mockRejectedValue(new Error("KeyStore operation failed"));

    StoreBiometricTokenBehavior.callback(
      behaviorElement({ token: "rotated-token" }),
      jest.fn(),
      jest.fn(),
      jest.fn(),
    );
    await new Promise(process.nextTick);

    // The server already invalidated the previous token when it issued this one, so
    // keeping the old value would strand the device on a credential nothing accepts.
    expect(mockStore.deleteItemAsync).toHaveBeenCalledTimes(1);
  });

  it.each([{ token: "rotated-token" }, { token: "" }])(
    "never leaks an unhandled rejection when the keystore fails (%p)",
    async (attributes) => {
      const rejections: unknown[] = [];
      const onRejection = (reason: unknown) => rejections.push(reason);
      process.on("unhandledRejection", onRejection);
      mockStore.setItemAsync.mockRejectedValue(new Error("keychain locked"));
      mockStore.deleteItemAsync.mockRejectedValue(new Error("keychain locked"));

      StoreBiometricTokenBehavior.callback(
        behaviorElement(attributes),
        jest.fn(),
        jest.fn(),
        jest.fn(),
      );
      await new Promise(process.nextTick);
      process.off("unhandledRejection", onRejection);

      expect(rejections).toEqual([]);
    },
  );
});

describe("the reset panel wipes before it probes", () => {
  it("never reveals the sign-in button while the wipe is still in flight", async () => {
    // The reset panel fires store-biometric-token (immediate, synchronous) and
    // probe-biometrics on the same load. They are two independent native calls:
    // if the read wins the race, the user gets a biometric button backed by a
    // token the server has already rejected, and pressing it does nothing.
    let stored: string | null = "rejected-token";
    mockStore.deleteItemAsync.mockImplementation(async () => {
      // A native delete does not resolve on the next microtask.
      for (let tick = 0; tick < 20; tick += 1) await Promise.resolve();
      stored = null;
    });
    mockStore.getItemAsync.mockImplementation(async () => stored);
    mockAuth.hasHardwareAsync.mockResolvedValue(true);
    mockAuth.isEnrolledAsync.mockResolvedValue(true);
    mockAuth.supportedAuthenticationTypesAsync.mockResolvedValue([2]);
    const doc = panel();

    StoreBiometricTokenBehavior.callback(
      behaviorElement({ token: "" }),
      jest.fn(),
      () => doc,
      jest.fn(),
    );
    const updateRoot = jest.fn();
    await ProbeBiometricsBehavior.callback(
      behaviorElement({
        "available-target": "biometric-optin",
        "token-target": "biometric-signin",
      }),
      jest.fn(),
      () => doc,
      updateRoot,
    );
    const newRoot = updateRoot.mock.calls[0][0] as Document;

    // The opt-in switch still has to appear: the copy tells the user to enrol again.
    expect(hideOf(newRoot, "biometric-optin")).toBe("false");
    expect(hideOf(newRoot, "biometric-signin")).toBe("true");
  });
});

describe("probe-biometrics", () => {
  const probe = behaviorElement({
    "available-target": "biometric-optin",
    "token-target": "biometric-signin",
  });

  async function runProbe(doc: Document, element: Element = probe) {
    const updateRoot = jest.fn();
    await ProbeBiometricsBehavior.callback(element, jest.fn(), () => doc, updateRoot);
    return updateRoot;
  }

  function switchValue(doc: Document): string | null {
    return (
      (doc.getElementById("biometric-optin-switch") as Element | null)?.getAttribute(
        "value",
      ) ?? null
    );
  }

  function iconHide(doc: Document): Record<string, string | null> {
    // The images carry NO id on purpose, so they are found by traversal, exactly
    // the way the behavior finds them.
    return Object.fromEntries(
      Array.from(doc.getElementsByTagName("image")).map((icon) => [
        icon.getAttribute("variant"),
        icon.getAttribute("hide"),
      ]),
    );
  }

  function enrolledWithToken(types?: number[]) {
    mockAuth.hasHardwareAsync.mockResolvedValue(true);
    mockAuth.isEnrolledAsync.mockResolvedValue(true);
    mockStore.getItemAsync.mockResolvedValue("issued-token");
    if (types) {
      mockAuth.supportedAuthenticationTypesAsync.mockResolvedValue(types);
    } else {
      mockAuth.supportedAuthenticationTypesAsync.mockRejectedValue(
        new Error("UnavailabilityError"),
      );
    }
  }

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it.each([
    [[2], "face"],
    [[1], "fingerprint"],
    [[1, 2], "fingerprint"],
    [[3], "fingerprint"],
  ])("shows only the glyph matching the reported modality (%p)", async (types, shown) => {
    enrolledWithToken(types);

    const updateRoot = await runProbe(panel());
    const newRoot = updateRoot.mock.calls[0][0] as Document;

    expect(updateRoot).toHaveBeenCalledTimes(1);
    expect(iconHide(newRoot)).toEqual({
      face: shown === "face" ? "false" : "true",
      fingerprint: shown === "fingerprint" ? "false" : "true",
    });
    expect(hideOf(newRoot, "biometric-signin")).toBe("false");
  });

  it.each([
    ["ios", "face"],
    ["android", "fingerprint"],
  ])("falls back to the %s glyph when the device reports nothing", async (os, shown) => {
    jest.replaceProperty(Platform, "OS", os as typeof Platform.OS);
    enrolledWithToken([]);

    const updateRoot = await runProbe(panel());
    const newRoot = updateRoot.mock.calls[0][0] as Document;

    expect(iconHide(newRoot)[shown]).toBe("false");
  });

  it("still reveals both controls when the modality probe throws", async () => {
    jest.replaceProperty(Platform, "OS", "ios");
    enrolledWithToken();

    const updateRoot = await runProbe(panel());
    const newRoot = updateRoot.mock.calls[0][0] as Document;

    expect(updateRoot).toHaveBeenCalledTimes(1);
    expect(hideOf(newRoot, "biometric-optin")).toBe("false");
    expect(hideOf(newRoot, "biometric-signin")).toBe("false");
    expect(iconHide(newRoot)).toEqual({ face: "false", fingerprint: "true" });
  });

  it("touches no glyph while the button itself stays hidden", async () => {
    mockAuth.hasHardwareAsync.mockResolvedValue(true);
    mockAuth.isEnrolledAsync.mockResolvedValue(true);
    mockAuth.supportedAuthenticationTypesAsync.mockResolvedValue([2]);
    const doc = panel();

    const updateRoot = await runProbe(doc);
    const newRoot = updateRoot.mock.calls[0][0] as Document;

    expect(hideOf(newRoot, "biometric-signin")).toBe("true");
    expect(iconHide(newRoot)).toEqual({ face: "true", fingerprint: "true" });
  });

  it("reveals nothing when the device has no biometric hardware", async () => {
    mockAuth.hasHardwareAsync.mockResolvedValue(false);
    mockAuth.isEnrolledAsync.mockResolvedValue(false);
    const doc = panel();

    const updateRoot = await runProbe(doc);

    expect(updateRoot).not.toHaveBeenCalled();
    expect(hideOf(doc, "biometric-optin")).toBe("true");
    expect(hideOf(doc, "biometric-signin")).toBe("true");
  });

  it("reveals nothing when no face or finger is enrolled", async () => {
    mockAuth.hasHardwareAsync.mockResolvedValue(true);
    mockAuth.isEnrolledAsync.mockResolvedValue(false);

    expect(await runProbe(panel())).not.toHaveBeenCalled();
  });

  it("reveals only the opt-in row when the device holds no token", async () => {
    mockAuth.hasHardwareAsync.mockResolvedValue(true);
    mockAuth.isEnrolledAsync.mockResolvedValue(true);
    const doc = panel();

    const updateRoot = await runProbe(doc);
    const newRoot = updateRoot.mock.calls[0][0] as Document;

    expect(updateRoot).toHaveBeenCalledTimes(1);
    expect(hideOf(newRoot, "biometric-optin")).toBe("false");
    expect(hideOf(newRoot, "biometric-signin")).toBe("true");
  });

  it("reveals the opt-in row and the unlock button when a token is stored", async () => {
    mockAuth.hasHardwareAsync.mockResolvedValue(true);
    mockAuth.isEnrolledAsync.mockResolvedValue(true);
    mockStore.getItemAsync.mockResolvedValue("issued-token");
    const doc = panel();

    const updateRoot = await runProbe(doc);
    const newRoot = updateRoot.mock.calls[0][0] as Document;

    expect(updateRoot).toHaveBeenCalledTimes(1);
    expect(hideOf(newRoot, "biometric-optin")).toBe("false");
    expect(hideOf(newRoot, "biometric-signin")).toBe("false");
  });

  it.each([null, "issued-token"])(
    "never pre-selects the opt-in switch, stored token %p or not",
    async (stored) => {
      // The stored key names a DEVICE, not a person. Pre-selecting from it enrolled
      // whoever signed in next on a shared phone, into an account that was not theirs.
      mockAuth.hasHardwareAsync.mockResolvedValue(true);
      mockAuth.isEnrolledAsync.mockResolvedValue(true);
      mockStore.getItemAsync.mockResolvedValue(stored);

      const updateRoot = await runProbe(panel());
      const newRoot = updateRoot.mock.calls[0][0] as Document;

      expect(updateRoot).toHaveBeenCalledTimes(1);
      expect(switchValue(newRoot)).toBe("off");
    },
  );

  it("never crashes the login screen when the native module throws", async () => {
    mockAuth.hasHardwareAsync.mockRejectedValue(new Error("no biometric service"));

    expect(await runProbe(panel())).not.toHaveBeenCalled();
  });
});

describe("biometric-unlock", () => {
  const button = behaviorElement({
    target: "biometric-token",
    "event-name": "biometric-authenticated",
    prompt: "Sign in to HyperTodo",
  });

  async function runUnlock(doc: Document) {
    const updateRoot = jest.fn();
    await BiometricUnlockBehavior.callback(button, jest.fn(), () => doc, updateRoot);
    return updateRoot;
  }

  function valueOf(doc: Document): string | null {
    return (doc.getElementById("biometric-token") as Element).getAttribute("value");
  }

  let dispatch: jest.SpyInstance;

  beforeEach(() => {
    dispatch = jest.spyOn(Events, "dispatch").mockImplementation(() => undefined);
  });

  afterEach(() => {
    dispatch.mockRestore();
  });

  it("writes the token into the hidden field and then dispatches the POST event", async () => {
    mockAuth.authenticateAsync.mockResolvedValue({ success: true });
    mockStore.getItemAsync.mockResolvedValue("issued-token");

    const updateRoot = await runUnlock(panel());
    const newRoot = updateRoot.mock.calls[0][0] as Document;

    expect(valueOf(newRoot)).toBe("issued-token");
    expect(dispatch).toHaveBeenCalledWith("biometric-authenticated");
    expect(updateRoot.mock.invocationCallOrder[0]).toBeLessThan(
      dispatch.mock.invocationCallOrder[0],
    );
  });

  it("gates the credential on biometrics only, never on the device passcode", async () => {
    // With disableDeviceFallback false the OS falls back to the passcode after a few
    // failures, so a shoulder-surfed passcode would open a 30-day account credential
    // while the button still says "Unlock with biometrics".
    mockAuth.authenticateAsync.mockResolvedValue({ success: true });
    mockStore.getItemAsync.mockResolvedValue("issued-token");

    await runUnlock(panel());

    expect(mockAuth.authenticateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ disableDeviceFallback: true }),
    );
  });

  it("passes the prompt copy authored in the HXML", async () => {
    mockAuth.authenticateAsync.mockResolvedValue({ success: true });
    mockStore.getItemAsync.mockResolvedValue("issued-token");

    await runUnlock(panel());

    expect(mockAuth.authenticateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ promptMessage: "Sign in to HyperTodo" }),
    );
  });

  const failures: LocalAuthentication.LocalAuthenticationError[] = [
    "user_cancel",
    "lockout",
    "not_enrolled",
  ];

  it.each(failures)(
    "does nothing when the prompt fails with %s",
    async (error) => {
      mockAuth.authenticateAsync.mockResolvedValue({ success: false, error });
      mockStore.getItemAsync.mockResolvedValue("issued-token");

      const updateRoot = await runUnlock(panel());

      expect(updateRoot).not.toHaveBeenCalled();
      expect(dispatch).not.toHaveBeenCalled();
    },
  );

  it("never posts an empty token when the device holds none", async () => {
    mockAuth.authenticateAsync.mockResolvedValue({ success: true });
    mockStore.getItemAsync.mockResolvedValue(null);

    const updateRoot = await runUnlock(panel());

    expect(updateRoot).not.toHaveBeenCalled();
    expect(dispatch).not.toHaveBeenCalled();
    expect(mockStore.deleteItemAsync).toHaveBeenCalled();
  });

  it("never dispatches when the native prompt throws", async () => {
    mockAuth.authenticateAsync.mockRejectedValue(new Error("no biometric service"));

    const updateRoot = await runUnlock(panel());

    expect(updateRoot).not.toHaveBeenCalled();
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("never writes the token anywhere but the hidden field", async () => {
    mockAuth.authenticateAsync.mockResolvedValue({ success: true });
    mockStore.getItemAsync.mockResolvedValue("issued-token");
    const logs: unknown[] = [];
    const spies = (["log", "warn", "error", "info", "debug"] as const).map((level) =>
      jest.spyOn(console, level).mockImplementation((...args) => logs.push(...args)),
    );

    await runUnlock(panel());
    spies.forEach((spy) => spy.mockRestore());

    expect(JSON.stringify(logs)).not.toContain("issued-token");
  });
});

describe("biometric-unlock feedback", () => {
  const button = behaviorElement({
    target: "biometric-token",
    "event-name": "biometric-authenticated",
    prompt: "Sign in to HyperTodo",
  });

  function collectNotices() {
    const notices: SnackbarNotice[] = [];
    const unsubscribe = subscribeToSnackbars((notice) => notices.push(notice));
    return { notices, unsubscribe };
  }

  async function runUnlock() {
    const collected = collectNotices();
    await BiometricUnlockBehavior.callback(button, jest.fn(), () => panel(), jest.fn());
    collected.unsubscribe();
    return collected.notices;
  }

  // The user dismissed the prompt on purpose, or chose the password form. Telling them
  // what they just did is noise.
  const intentional: LocalAuthentication.LocalAuthenticationError[] = ["user_cancel", "user_fallback", "app_cancel", "system_cancel"];

  it.each(intentional)("stays quiet when the user dismisses the prompt (%s)", async (error) => {
    mockAuth.authenticateAsync.mockResolvedValue({ success: false, error });

    expect(await runUnlock()).toEqual([]);
  });

  // In Expo Go on a Face ID iPhone the native module refuses before showing anything,
  // because Expo Go's own bundle carries no NSFaceIDUsageDescription. Without feedback the
  // button looks dead, which is exactly how this surfaced.
  // "missing_usage_description" is absent from expo-local-authentication 57.0.2's exported
  // LocalAuthenticationError union, but LocalAuthenticationModule.swift:96 really returns it.
  // Typed as string and widened at the mock so the Expo Go case stays under test.
  const unexpected = ["missing_usage_description", "lockout", "not_enrolled", "authentication_failed"];

  it.each(unexpected)("explains a failure the user did not choose (%s)", async (error) => {
    mockAuth.authenticateAsync.mockResolvedValue({
      success: false,
      error: error as LocalAuthentication.LocalAuthenticationError,
    });

    const notices = await runUnlock();

    expect(notices).toHaveLength(1);
    expect(notices[0].tone).toBe("error");
    expect(notices[0].message).not.toContain(error);
    expect(notices[0].message).toMatch(/password/i);
  });

  it("explains a native crash instead of looking dead", async () => {
    mockAuth.authenticateAsync.mockRejectedValue(new Error("LAError -1000"));

    const notices = await runUnlock();

    expect(notices).toHaveLength(1);
    expect(notices[0].tone).toBe("error");
    expect(notices[0].message).not.toContain("LAError");
  });
});

describe("biometric-unlock diagnostics", () => {
  const button = behaviorElement({
    target: "biometric-token",
    "event-name": "biometric-authenticated",
    prompt: "Sign in to HyperTodo",
  });

  let logged: jest.SpyInstance;

  beforeEach(() => {
    logged = jest.spyOn(hyperviewLogger, "warn").mockImplementation(() => undefined);
  });

  afterEach(() => {
    logged.mockRestore();
  });

  async function runUnlock() {
    await BiometricUnlockBehavior.callback(button, jest.fn(), () => panel(), jest.fn());
  }

  // The user-facing copy is deliberately generic, which leaves a developer with nothing to
  // debug. The specific reason belongs in the log, where it reaches Metro without raising a
  // LogBox overlay. "missing_usage_description" is the Expo Go case on a Face ID iPhone.
  it("records the exact reason a prompt was refused", async () => {
    mockAuth.authenticateAsync.mockResolvedValue({
      success: false,
      error: "missing_usage_description" as LocalAuthentication.LocalAuthenticationError,
    });

    await runUnlock();

    expect(logged).toHaveBeenCalledWith(expect.any(String), "missing_usage_description");
  });

  it("records a dismissal too, even though the user sees nothing", async () => {
    mockAuth.authenticateAsync.mockResolvedValue({ success: false, error: "user_cancel" });

    await runUnlock();

    expect(logged).toHaveBeenCalledWith(expect.any(String), "user_cancel");
  });

  it("records a native crash", async () => {
    const crash = new Error("LAError -1000");
    mockAuth.authenticateAsync.mockRejectedValue(crash);

    await runUnlock();

    expect(logged).toHaveBeenCalledWith(expect.any(String), crash);
  });
});
