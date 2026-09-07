import * as LocalAuthentication from "expo-local-authentication";
import type { HvBehavior } from "hyperview";
import { dispatch } from "hyperview/src/services/events";
import { getElementById } from "hyperview/src/services/dom";
import { shallowCloneToRoot } from "hyperview/src/services";

import { clearToken, readToken } from "../biometrics/store";
import { hyperviewLogger } from "../feedback/logging";
import { publishSnackbar } from "../feedback/snackbar";

// Dismissing the prompt, or choosing the password form through `cancelLabel`, is a decision
// the user just made. Narrating it back is noise. Every other failure is unexpected from
// where they are standing, and staying silent makes the button look dead -- which is how a
// Face ID device running Expo Go presents, since Expo Go's own bundle carries no
// NSFaceIDUsageDescription and the native module refuses before showing anything.
const INTENTIONAL_DISMISSALS = new Set([
  "app_cancel",
  "system_cancel",
  "user_cancel",
  "user_fallback",
]);

// User-facing, so no error codes and no native vocabulary: it names the way out instead.
const UNLOCK_FAILED = "Biometric unlock isn't available right now. Sign in with your password.";

// Deliberately NOT once="true" in HXML: the user must be able to retry after
// cancelling the prompt.
const BiometricUnlockBehavior: HvBehavior = {
  action: "biometric-unlock",
  callback: async (element, _onUpdate, getRoot, updateRoot) => {
    try {
      const result = await LocalAuthentication.authenticateAsync({
        cancelLabel: "Use password",
        // Biometrics only. With the default `false` the OS falls back to the device
        // passcode after a few failures (LAPolicyDeviceOwnerAuthentication), so a
        // shoulder-surfed passcode would open a 30-day account credential while the
        // copy on screen promises "Unlock with biometrics". The password form is the
        // fallback, and `cancelLabel` points at it.
        disableDeviceFallback: true,
        promptMessage: element.getAttribute("prompt") ?? "Sign in to HyperTodo",
      });
      if (!result.success) {
        // The copy above is deliberately generic, which leaves a developer with nothing to
        // debug. The specific reason goes to the log instead, where it reaches Metro without
        // raising a LogBox overlay. Expect "missing_usage_description" in Expo Go on a Face ID
        // device: config plugins write NSFaceIDUsageDescription into YOUR app's Info.plist at
        // prebuild, and Expo Go runs its own binary, so the native module refuses up front.
        hyperviewLogger.warn("biometric unlock refused:", result.error);
        if (!INTENTIONAL_DISMISSALS.has(result.error)) {
          publishSnackbar({ message: UNLOCK_FAILED, tone: "error" });
        }
        return;
      }
      const token = await readToken();
      if (!token) {
        // Enrolment was revoked or the keychain entry is gone: leave the device clean
        // rather than posting an empty token the server would only reject.
        await clearToken();
        return;
      }
      const field = getElementById(getRoot(), element.getAttribute("target") ?? "");
      if (!field) {
        return;
      }
      // getNameValueFormInputValues reads the `value` ATTRIBUTE, so this is what the
      // sibling on-event behavior serializes into the POST.
      field.setAttribute("value", token);
      updateRoot(shallowCloneToRoot(field));
      // Dispatch last: the POST must see the written field.
      dispatch(element.getAttribute("event-name") ?? "");
    } catch (error) {
      // A native failure leaves the password form untouched and usable, but the user still
      // pressed a button, so say something rather than nothing.
      hyperviewLogger.warn("biometric unlock crashed:", error);
      publishSnackbar({ message: UNLOCK_FAILED, tone: "error" });
    }
  },
};

export default BiometricUnlockBehavior;
