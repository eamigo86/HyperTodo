import type {StorageQueue} from "../realtime/session-effects";
import * as SecureStore from "expo-secure-store";

// One key per device: the newest sign-in owns the device, matching the server's
// one-credential-per-user model. The value is a server-issued rotating token,
// never a password, and it is never logged.
const TOKEN_KEY = "hypertodo.biometric.token";

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

/** Internal composition point: a port built on another key never reads the normal app credential. */
export function createSessionCredentialPort(key:string):{read():Promise<string|null>;storage:StorageQueue} {
  if(!key)throw new Error("missing-credential-key");
  return Object.freeze({
    // Failures reach the caller: a failed read must never look like a missing token.
    read:()=>serialized(()=>SecureStore.getItemAsync(key)),
    storage:{enqueue:job=>serialized(()=>job({
      // requireAuthentication is deliberately unset: it is unsupported in Expo Go and
      // redundant here, because we run the biometric prompt explicitly before reading.
      // keychainAccessible is NOT optional: the default is WHEN_UNLOCKED, which migrates
      // with an iCloud backup, and the server binds this token to a user but never to a
      // device. A restored backup would be a working credential on someone else's phone.
      save:token=>SecureStore.setItemAsync(key,token,{keychainAccessible:SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY}),
      clear:()=>SecureStore.deleteItemAsync(key),
    }))},
  });
}

/** Normal App composition preserves its existing device-only credential key. */
export const sessionCredentials=createSessionCredentialPort(TOKEN_KEY);
