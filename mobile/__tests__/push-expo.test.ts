import Constants from "expo-constants";
import * as Notifications from "expo-notifications";
import * as SecureStore from "expo-secure-store";
import {Platform} from "react-native";
import {createExpoPushPorts} from "../src/push/expo";

jest.mock("expo-constants", () => ({__esModule: true, default: {
  appOwnership: null, easConfig: {projectId: "project-id"}, expoConfig: {extra: {}},
}}));
jest.mock("expo-crypto", () => ({randomUUID: () => "11111111-1111-4111-8111-111111111111"}));
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 6, getItemAsync: jest.fn(), setItemAsync: jest.fn(),
}));
jest.mock("expo-notifications", () => ({
  AndroidImportance: {DEFAULT: 3},
  setNotificationHandler: jest.fn(), setNotificationChannelAsync: jest.fn(async () => {}),
  getPermissionsAsync: jest.fn(async () => ({granted: true, canAskAgain: true})),
  requestPermissionsAsync: jest.fn(async () => ({granted: true})),
  getExpoPushTokenAsync: jest.fn(async () => ({data: "ExpoPushToken[safe]"})),
  addPushTokenListener: jest.fn(() => ({remove: jest.fn()})),
  addNotificationResponseReceivedListener: jest.fn(() => ({remove: jest.fn()})),
  getLastNotificationResponseAsync: jest.fn(async () => null),
}));

beforeEach(() => {
  jest.clearAllMocks();
  (Constants as {appOwnership: string | null}).appOwnership = null;
});

test("does not ask for remote push in Expo Go", async () => {
  (Constants as {appOwnership: string | null}).appOwnership = "expo";
  const ports = createExpoPushPorts();
  expect(await ports.supported()).toBe(false);
  expect(Notifications.getPermissionsAsync).not.toHaveBeenCalled();
});

test("suppresses foreground alerts and converts the provided native token", async () => {
  const ports = createExpoPushPorts();
  expect(await ports.supported()).toBe(true);
  expect(await ports.permission()).toBe(true);
  expect(Notifications.setNotificationHandler).toHaveBeenCalledWith({handleNotification: expect.any(Function)});
  const handler = (Notifications.setNotificationHandler as jest.Mock).mock.calls[0][0].handleNotification;
  expect(await handler()).toEqual({shouldPlaySound: false, shouldSetBadge: false, shouldShowBanner: false, shouldShowList: false});
  const native = {type: "android", data: "fcm-token"};
  expect(await ports.getToken(native)).toBe("ExpoPushToken[safe]");
  expect(Notifications.getExpoPushTokenAsync).toHaveBeenCalledWith({projectId: "project-id", devicePushToken: native});
  expect(await ports.getToken({type: "web", data: "bad"})).toBeNull();
  expect(Notifications.getExpoPushTokenAsync).toHaveBeenCalledTimes(1);
});

test("forwards only the native token and bounded tap data", async () => {
  const ports = createExpoPushPorts();
  const token = jest.fn(), tap = jest.fn();
  const stopToken = ports.onToken(token), stopTap = ports.onTap(tap);
  await Promise.resolve(); await Promise.resolve();
  (Notifications.addPushTokenListener as jest.Mock).mock.calls[0][0]({type: "ios", data: "apns"});
  (Notifications.addNotificationResponseReceivedListener as jest.Mock).mock.calls[0][0]({
    notification: {request: {identifier: "tap-1", content: {data: {kind: "tasks"}}}},
  });
  expect(token).toHaveBeenCalledWith({type: "ios", data: "apns"});
  expect(tap).toHaveBeenCalledWith({id: "tap-1", data: {kind: "tasks"}});
  stopToken(); stopTap();
  expect((Notifications.addPushTokenListener as jest.Mock).mock.results[0].value.remove).toHaveBeenCalled();
});

test("stores installation and registration separately from biometric credentials", async () => {
  const ports = createExpoPushPorts();
  (SecureStore.getItemAsync as jest.Mock).mockResolvedValueOnce(null).mockResolvedValueOnce("not-json");
  expect(await ports.readInstallation()).toBeNull();
  expect(ports.newInstallationId()).toBe("11111111-1111-4111-8111-111111111111");
  await ports.saveInstallation("installation");
  expect(await ports.readRegistration()).toBeNull();
  const record = {binding: "session", expoToken: "ExpoPushToken[safe]", registrationVersion: "revision"};
  await ports.saveRegistration(record);
  expect((SecureStore.setItemAsync as jest.Mock).mock.calls.map(call => call[0])).toEqual([
    "hypertodo.push.installation.v1", "hypertodo.push.registration.v1",
  ]);
  expect((SecureStore.setItemAsync as jest.Mock).mock.calls.every(call => call[2].keychainAccessible === 6)).toBe(true);
});

test("permission refusal never requests a new token and Android creates its channel first", async () => {
  const previous = Platform.OS;
  Object.defineProperty(Platform, "OS", {value: "android", configurable: true});
  try {
    const ports = createExpoPushPorts();
    (Notifications.getPermissionsAsync as jest.Mock).mockResolvedValueOnce({granted: false, canAskAgain: false});
    expect(await ports.permission()).toBe(false);
    expect(Notifications.setNotificationChannelAsync).toHaveBeenCalledWith("default", {name: "Default", importance: 3});
    expect(Notifications.requestPermissionsAsync).not.toHaveBeenCalled();
    (Notifications.getPermissionsAsync as jest.Mock).mockResolvedValue({granted: false, canAskAgain: true});
    (Notifications.requestPermissionsAsync as jest.Mock).mockResolvedValueOnce({granted: false});
    expect(await ports.permission()).toBe(false);
    expect(await ports.permission()).toBe(false);
    expect(Notifications.requestPermissionsAsync).toHaveBeenCalledTimes(1);
    expect(Notifications.getExpoPushTokenAsync).not.toHaveBeenCalled();
  } finally {
    Object.defineProperty(Platform, "OS", {value: previous, configurable: true});
  }
});

test("web and malformed native tokens are not registered", async () => {
  const previous = Platform.OS;
  Object.defineProperty(Platform, "OS", {value: "web", configurable: true});
  try { expect(await createExpoPushPorts().supported()).toBe(false); }
  finally { Object.defineProperty(Platform, "OS", {value: previous, configurable: true}); }
  const ports = createExpoPushPorts();
  expect(await ports.getToken()).toBe("ExpoPushToken[safe]");
  for (const value of [null, {}, {type: "ios"}, {type: "android", data: 4}]) {
    expect(await ports.getToken(value)).toBeNull();
  }
  expect(Notifications.getExpoPushTokenAsync).toHaveBeenCalledTimes(1);
});

test("a disposed listener cannot be installed after its native import settles", async () => {
  const ports = createExpoPushPorts();
  ports.onToken(jest.fn())();
  ports.onTap(jest.fn())();
  await Promise.resolve(); await Promise.resolve();
  expect(Notifications.addPushTokenListener).not.toHaveBeenCalled();
  expect(Notifications.addNotificationResponseReceivedListener).not.toHaveBeenCalled();
});

test("reads the last notification and validates the shape of cached registration", async () => {
  const ports = createExpoPushPorts();
  (Notifications.getLastNotificationResponseAsync as jest.Mock).mockResolvedValueOnce({
    notification: {request: {identifier: "cold", content: {data: {kind: "tasks"}}}},
  });
  expect(await ports.lastTap()).toEqual({id: "cold", data: {kind: "tasks"}});
  (SecureStore.getItemAsync as jest.Mock)
    .mockResolvedValueOnce(JSON.stringify({binding: "session", expoToken: "token", registrationVersion: "revision"}))
    .mockResolvedValueOnce("[]")
    .mockResolvedValueOnce(JSON.stringify({binding: "session"}));
  expect(await ports.readRegistration()).toEqual({binding: "session", expoToken: "token", registrationVersion: "revision"});
  expect(await ports.readRegistration()).toBeNull();
  expect(await ports.readRegistration()).toBeNull();
});
