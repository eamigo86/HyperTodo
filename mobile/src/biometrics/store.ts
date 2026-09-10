import type {StorageQueue} from "../realtime/session-effects";
import * as LocalAuthentication from "expo-local-authentication";
import { AuthenticationType } from "expo-local-authentication";
import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";

// One key per device: the newest sign-in owns the device, matching the server's
// one-credential-per-user model. The value is a server-issued rotating token,
// never a password, and it is never logged.
const TOKEN_KEY = "hypertodo.biometric.token";

export async function hasEnrolledBiometrics(): Promise<boolean> {
  return (
    (await LocalAuthentication.hasHardwareAsync()) &&
    (await LocalAuthentication.isEnrolledAsync())
  );
}

export type BiometricIcon = "face" | "fingerprint";

export async function preferredBiometricIcon(): Promise<BiometricIcon> {
  // Branch on what the device REPORTS, not on the platform: a Touch ID iPhone
  // reports [FINGERPRINT] and a face-unlock Android reports [FACIAL_RECOGNITION],
  // so Platform gets it backwards on both.
  try {
    const types = await LocalAuthentication.supportedAuthenticationTypesAsync();
    if (types.length === 1 && types[0] === AuthenticationType.FACIAL_RECOGNITION) {
      return "face";
    }
    // Only Android reports several, and it reports HARDWARE presence rather than
    // enrolment (LocalAuthenticationModule.kt:292), so fingerprint — the Class 3
    // modality people actually enrol — is the safer glyph.
    if (types.length > 0) {
      return "fingerprint";
    }
  } catch {
    // The native method is missing entirely (UnavailabilityError).
  }
  // Nothing reported: iOS Optic ID, which the native module never maps
  // (LocalAuthenticationModule.swift:26-38), or Android with no hardware feature
  // string it recognises (kt:39-49). Platform is the only signal left.
  return Platform.OS === "ios" ? "face" : "fingerprint";
}

// Every keystore call goes through one chain. They are independent native calls,
// so a wipe and a read started in the same document load complete in either
// order, and the reset login panel starts exactly that pair: store-biometric-token
// clears while probe-biometrics reads. A read that wins reveals a sign-in button
// backed by a token the server has already rejected, and pressing it does nothing.
let queue: Promise<unknown> = Promise.resolve();

function serialized<T>(operation: () => Promise<T>): Promise<T> {
  // Both handlers, so a rejected predecessor still runs the next operation.
  const result = queue.then(operation, operation);
  queue = result.catch(() => undefined);
  return result;
}

export async function readToken(): Promise<string | null> {
  try {
    return await serialized(() => SecureStore.getItemAsync(TOKEN_KEY));
  } catch {
    return null;
  }
}

export async function saveToken(token: string): Promise<void> {
  // requireAuthentication is deliberately unset: it is unsupported in Expo Go and
  // redundant here, because we run the biometric prompt explicitly before reading.
  // keychainAccessible is NOT optional: the default is WHEN_UNLOCKED, which migrates
  // with an iCloud backup, and the server binds this token to a user but never to a
  // device. A restored backup would be a working credential on someone else's phone.
  await serialized(() =>
    SecureStore.setItemAsync(TOKEN_KEY, token, {
      keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    }),
  );
}

export async function clearToken(): Promise<void> {
  try {
    await serialized(() => SecureStore.deleteItemAsync(TOKEN_KEY));
  } catch {
    // Nothing left to fall back to. The device keeps a token the server rejects,
    // which the next unlock attempt turns into a reset panel anyway.
  }
}


/** Internal composition point: fixture keys never read the normal app credential. */
export function createSessionCredentialPort(key:string):{read():Promise<string|null>;storage:StorageQueue} {
  if(!key)throw new Error("missing-credential-key");
  return Object.freeze({
    // Unlike legacy readToken/clearToken, modern ownership observes failures.
    read:()=>serialized(()=>SecureStore.getItemAsync(key)),
    storage:{enqueue:job=>serialized(()=>job({
      save:token=>SecureStore.setItemAsync(key,token,{keychainAccessible:SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY}),
      clear:()=>SecureStore.deleteItemAsync(key),
    }))},
  });
}

/** Normal App composition preserves its existing device-only credential key. */
export const sessionCredentials=createSessionCredentialPort(TOKEN_KEY);
export const sessionStorageQueue=sessionCredentials.storage;
