import type { HvBehavior } from "hyperview";

import { clearToken, saveToken } from "../biometrics/store";

// One behavior serves issuance and revocation: an absent or blank `token`
// attribute means "this device no longer holds a credential".
const StoreBiometricTokenBehavior: HvBehavior = {
  action: "store-biometric-token",
  callback: (element) => {
    const token = element.getAttribute("token")?.trim();
    // A keystore write can reject (locked keychain, changed lock screen). The server
    // has already invalidated the previous token by issuing this one, so falling back
    // to a clear leaves the device unenrolled instead of holding a dead credential.
    // clearToken never rejects, so nothing escapes as an unhandled rejection.
    void (token ? saveToken(token).catch(clearToken) : clearToken());
  },
};

export default StoreBiometricTokenBehavior;
