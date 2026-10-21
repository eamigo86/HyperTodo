import Constants from "expo-constants";
import * as Crypto from "expo-crypto";
import * as SecureStore from "expo-secure-store";
import * as Notifications from "expo-notifications";
import {Platform} from "react-native";
import type {PushPorts, PushRegistration} from "./coordinator";

const INSTALLATION_KEY = "hypertodo.push.installation.v1";
const REGISTRATION_KEY = "hypertodo.push.registration.v1";
const PROJECT_ID = Constants.easConfig?.projectId ?? Constants.expoConfig?.extra?.eas?.projectId;
let queue: Promise<unknown> = Promise.resolve();
let handlerSet = false;

function serialized<T>(operation: () => Promise<T>): Promise<T> {
  const result = queue.then(operation, operation);
  queue = result.catch(() => undefined);
  return result;
}

async function notifications() {
  return Notifications;
}

function extractResponse(response: unknown) {
  if (!response || typeof response !== "object") return null;
  const candidate = response as {notification?: {request?: {identifier?: unknown; content?: {data?: unknown}}}};
  return {id: candidate.notification?.request?.identifier, data: candidate.notification?.request?.content?.data};
}

/** Optional native boundary: absence of project/native support never blocks the app. */
export function createExpoPushPorts(): PushPorts {
  let permissionRequested = false;
  return {
    async supported() {
      return Platform.OS !== "web" && Constants.appOwnership !== "expo"
        && typeof PROJECT_ID === "string" && PROJECT_ID.length > 0;
    },
    async permission() {
      const module = await notifications();
      if (!handlerSet) {
        module.setNotificationHandler({handleNotification: async () => ({
          shouldPlaySound: false, shouldSetBadge: false, shouldShowBanner: false, shouldShowList: false,
        })});
        handlerSet = true;
      }
      if (Platform.OS === "android") {
        await module.setNotificationChannelAsync("default", {name: "Default", importance: module.AndroidImportance.DEFAULT});
      }
      const current = await module.getPermissionsAsync();
      if (current.granted) return true;
      if (!current.canAskAgain || permissionRequested) return false;
      permissionRequested = true;
      return (await module.requestPermissionsAsync()).granted;
    },
    async getToken(deviceToken?: unknown) {
      const module = await notifications();
      if (deviceToken !== undefined && (!deviceToken || typeof deviceToken !== "object"
        || !("type" in deviceToken) || !("data" in deviceToken)
        || !["ios", "android"].includes(String(deviceToken.type)) || typeof deviceToken.data !== "string")) return null;
      const options = deviceToken === undefined ? {projectId: PROJECT_ID} : {
        projectId: PROJECT_ID,
        devicePushToken: deviceToken as {type: "ios" | "android"; data: string},
      };
      return (await module.getExpoPushTokenAsync(options)).data;
    },
    onToken(callback) {
      let active = true;
      let remove = () => {};
      void notifications().then(module => {
        if (!active) return;
        const subscription = module.addPushTokenListener(token => callback(token));
        remove = () => subscription.remove();
      }).catch(() => {});
      return () => {active = false; remove();};
    },
    onTap(callback) {
      let active = true;
      let remove = () => {};
      void notifications().then(module => {
        if (!active) return;
        const subscription = module.addNotificationResponseReceivedListener(response => callback(extractResponse(response)));
        remove = () => subscription.remove();
      }).catch(() => {});
      return () => {active = false; remove();};
    },
    async lastTap() {
      return extractResponse(await (await notifications()).getLastNotificationResponseAsync());
    },
    readInstallation: () => serialized(() => SecureStore.getItemAsync(INSTALLATION_KEY)),
    saveInstallation: value => serialized(() => SecureStore.setItemAsync(INSTALLATION_KEY, value, {
      keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    })),
    readRegistration: () => serialized(async () => {
      const raw = await SecureStore.getItemAsync(REGISTRATION_KEY);
      if (!raw) return null;
      try {
        const value: unknown = JSON.parse(raw);
        if (value && typeof value === "object" && !Array.isArray(value)) {
          const record = value as Partial<PushRegistration>;
          if (typeof record.binding === "string" && typeof record.expoToken === "string"
            && typeof record.registrationVersion === "string") return record as PushRegistration;
        }
      } catch { /* Treat malformed local cache as absent. */ }
      return null;
    }),
    saveRegistration: value => serialized(() => SecureStore.setItemAsync(REGISTRATION_KEY, JSON.stringify(value), {
      keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    })),
    newInstallationId: () => Crypto.randomUUID(),
  };
}
