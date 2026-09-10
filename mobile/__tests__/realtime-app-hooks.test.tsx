import "react-native-gesture-handler/jestSetup";
declare const __dirname: string; // Supplied by this Jest module, not the native App.
import React from "react";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { AppState } from "react-native";
import { NavigationContainer } from "@react-navigation/native";
import { createStackNavigator } from "@react-navigation/stack";
import { createSessionApp } from "../App";
import { createAppSession, AppSessionSurface, type AppSessionOptions } from "../src/realtime/app-session";
import { createThemeStore, ThemeProvider } from "../src/theme";
import { SESSION_HEADERS as H } from "../src/realtime/session-protocol";
import { subscribeToNetworkFailures } from "../src/feedback/failure";
import { hyperviewLogger } from "../src/feedback/logging";

jest.mock("expo-splash-screen", () => ({ preventAutoHideAsync: jest.fn(), hideAsync: jest.fn() }));
jest.mock("lottie-react-native", () => {
  const React = jest.requireActual("react"), { View } = jest.requireActual("react-native");
  return { __esModule: true, default: React.forwardRef((props: any, ref: any) => {
    React.useImperativeHandle(ref, () => ({ play: () => props.onAnimationFinish?.(false), reset: () => {} }));
    return <View {...props} />;
  }) };
});
jest.mock("react-native-safe-area-context", () => jest.requireActual("react-native-safe-area-context/jest/mock").default);
jest.mock("react-native-webview", () => ({ WebView: () => null }));
jest.mock("expo-secure-store", () => ({ getItem: jest.fn(() => null), setItem: jest.fn() }));
const initialAppState = AppState.currentState;
beforeEach(() => { AppState.currentState = "active"; });
afterEach(() => { AppState.currentState = initialAppState; jest.restoreAllMocks(); });

const ENTRY = "https://app.test/hv/", HV = "https://hyperview.org/hyperview", NS = "https://hypertodo.app/components";
const A = "hvs1." + "A".repeat(43), B = "hvs1." + "B".repeat(43);
const transition = jest.requireActual("fs").readFileSync(jest.requireActual("path").resolve(__dirname, "../../backend/hyperview/fragments/login_transition.xml"), "utf8").replace("{{ biometric_token }}", "t".repeat(43));
const root = (href = "/hv/tasks/") => `<doc xmlns="${HV}"><navigator id="root" type="stack"><nav-route id="tasks" href="${href}"/></navigator></doc>`;
const doc = (id: string, name: string) => `<doc xmlns="${HV}" xmlns:app="${NS}"><screen><body><app:realtime refresh-href="/hv/tasks/?category=7" target="main" mode="notice" resources="tasks categories"><view id="main"><app:realtime-page request-id="${id}" page="1"/><text>${name}</text><form><text-field name="title" placeholder="Draft" value="kept"/><view href="/hv/append/" action="append" target="rows"><text>Append</text></view></form><view id="rows"/><view id="login-panel"><form><text-field name="username" value="fictional" hide="true"/><text-field name="password" value="fictional" hide="true"/><view href="/hv/login/" verb="post" action="replace" target="login-panel"><text>Sign in B</text></view></form></view></view></app:realtime></body></screen></doc>`;
function response(body: string, binding: string, url: string, status = 200) {
  const result = new Response(body, { status, headers: { [H.binding]: binding, "Content-Type": "application/vnd.hyperview+xml" } });
  Object.defineProperty(result, "url", { value: url });
  return result;
}
function fixture(hooks: Partial<AppSessionOptions> = {}) {
  let binding = A, authenticated = false, release: (() => void) | undefined, hold = false, fail = false;
  const events: unknown[] = [], receivers: unknown[] = [];
  const onGateObservation = jest.fn((event: unknown) => { events.push(event); });
  const onResourceReceiver = jest.fn((receiver: unknown) => { receivers.push(receiver); });
  const http = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("session-state/")) return response(JSON.stringify({ version: 1, authenticated, binding }), binding, url);
    if (fail) throw new Error("private request context must not be logged");
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    if (url.endsWith("/login/") && init?.method?.toUpperCase() === "POST") {
      binding = B; authenticated = true;
      const result = response(transition, B, url);
      result.headers.set(H.outcome, "password-ok");
      return result;
    }
    if (url === ENTRY) return response(root(), binding, url);
    if (url.endsWith("/recovery/")) return response(root("/hv/recovery/?screen=login"), binding, url);
    if (url.includes("/append/")) return response(`<view xmlns="${HV}" xmlns:app="${NS}"><app:realtime-page request-id="${id}" page="1"/><text>Appended</text></view>`, binding, url);
    const result = response(doc(id, url.includes("recovery") ? "Public login" : binding === A ? "Private A" : "Private B"), binding, url);
    if (hold) {
      const original = result.text.bind(result);
      result.text = async () => { await new Promise<void>(resolve => { release = resolve; }); return original(); };
    }
    return result;
  });
  const storage = { enqueue: async (job: any) => job({ save: jest.fn(async () => {}), clear: jest.fn(async () => {}) }) };
  const options: AppSessionOptions = {
    entrypointUrl: ENTRY, http, credentials: { read: async () => null, storage },
    native: { platform: "ios", hasHardware: async () => false, isEnrolled: async () => false, supportedTypes: async () => [], readToken: async () => null, unlock: async () => ({ success: false }), pick: async () => ({ canceled: true }), render: jest.fn(), save: jest.fn() },
    onTheme: jest.fn(), onNotice: jest.fn(), stopStream: jest.fn(), onGateObservation, onResourceReceiver, ...hooks,
  };
  const session = createAppSession(options);
  return { session, options, events, receivers, onGateObservation, onResourceReceiver, http,
    hold: () => { hold = true; }, release: () => { hold = false; release?.(); }, waiting: () => !!release,
    switchBinding: () => { binding = B; }, fail: () => { fail = true; } };
}
const Stack = createStackNavigator();
function mount(f: ReturnType<typeof fixture>) {
  return render(<ThemeProvider store={createThemeStore({ read: () => null, write: () => {} })}><NavigationContainer><Stack.Navigator screenOptions={{ animationEnabled: false }}><Stack.Screen name="host">{() => <AppSessionSurface session={f.session} hyperviewProps={{ formatDate: () => undefined }} />}</Stack.Screen></Stack.Navigator></NavigationContainer></ThemeProvider>);
}

it("publishes only committed ready/terminal observations and exposes no ACK authority", async () => {
  const f = fixture(); f.hold(); const ui = mount(f);
  try {
    await waitFor(() => expect(f.waiting()).toBe(true));
    expect(f.events).toEqual([]);
    expect(f.receivers.filter(Boolean)).toEqual([]);
    await act(async () => f.release());
    await ui.findByText("Private A");
    await waitFor(() => expect(f.events.some((event: any) => event.kind === "ready")).toBe(true));
    for (const event of f.events as any[]) {
      expect(Object.isFrozen(event)).toBe(true);
      expect(Object.values(event).every(value => value === null || ["string", "number"].includes(typeof value))).toBe(true);
      expect(Object.keys(event).sort()).toEqual(event.kind === "ready" ? ["epoch", "kind", "routeKey"] : ["epoch", "kind", "operation", "outcome", "reason", "routeKey"]);
    }
    fireEvent.press(ui.getByText("Append"));
    await ui.findByText("Appended");
    await waitFor(() => expect(f.events.some((event: any) => event.kind === "terminal" && event.reason === "remote-layout")).toBe(true));
  } finally { ui.unmount(); f.session.dispose(); }
});

it("revokes published and previously captured receivers on pause, uncertainty, recovery and disposal", async () => {
  const f = fixture(), ui = mount(f);
  try {
    await ui.findByText("Private A");
    await waitFor(() => expect(f.onResourceReceiver).toHaveBeenCalledWith(expect.any(Function)));
    const receiver = f.session.captureResources()!;
    const rootInstance = ui.UNSAFE_getByType(f.session.gate.Root);
    fireEvent.changeText(ui.getByPlaceholderText("Draft"), "own draft");
    act(() => f.session.pause());
    expect(f.receivers.at(-1)).toBe(null);
    expect(receiver(["tasks"])).toBe(false);
    await act(async () => { await f.session.foreground(); });
    expect(ui.UNSAFE_getByType(f.session.gate.Root)).toBe(rootInstance);
    expect(ui.getByPlaceholderText("Draft").props.value).toBe("own draft");
    await waitFor(() => expect(f.receivers.at(-1)).toEqual(expect.any(Function)));
    act(() => { expect(receiver(["tasks"])).toBe(true); });
    expect(ui.UNSAFE_getByType(f.session.gate.Root)).toBe(rootInstance);
    expect(ui.getByPlaceholderText("Draft").props.value).toBe("own draft");
    f.switchBinding();
    await act(async () => { f.session.pause(); await f.session.foreground(); });
    expect(receiver(["tasks"])).toBe(false);
    expect(f.receivers.at(-1)).toBe(null);
    const beforeRecovery = f.events.length;
    await act(async () => { await f.session.beginRecovery(); });
    await ui.findByText("Public login");
    expect(f.session.captureResources()).toBe(null);
    expect(f.receivers.at(-1)).toBe(null);
    expect(receiver(["tasks"])).toBe(false);
    const publicGate = f.session.snapshot().recovery!.gate;
    await waitFor(() => expect(f.events.slice(beforeRecovery).some((event: any) => event.kind === "ready" && event.epoch === publicGate.snapshot().epoch)).toBe(true));
    act(() => f.session.dispose());
    expect(f.receivers.at(-1)).toBe(null);
    expect(receiver(["tasks"])).toBe(false);
  } finally { ui.unmount(); f.session.dispose(); }
});

it("contains observer/receiver exceptions without changing real layout, requests or draft", async () => {
  const observed = jest.fn(() => { throw new Error("observer failed"); });
  const receiver = jest.fn(() => { throw new Error("receiver failed"); });
  const f = fixture({ onGateObservation: observed, onResourceReceiver: receiver }), ui = mount(f);
  try {
    await ui.findByText("Private A");
    expect(f.session.snapshot().session.rootReady).toBe(true);
    expect(observed).toHaveBeenCalled(); expect(receiver).toHaveBeenCalled();
    fireEvent.press(ui.getByText("Append"));
    await ui.findByText("Appended");
    expect(f.http.mock.calls.filter(([url]) => String(url).includes("append"))).toHaveLength(1);
  } finally { ui.unmount(); f.session.dispose(); }
});

it("supplies fixture-only diagnostics without raw default logging and preserves the real error UI", async () => {
  const f = fixture(); f.fail();
  const codes: string[] = [], failures = jest.fn(), unsubscribe = subscribeToNetworkFailures(failures);
  const defaultLog = jest.spyOn(hyperviewLogger, "error").mockImplementation(() => {});
  const diagnostics = {
    logger: { error: (..._args: unknown[]) => { codes.push("sdk-error"); throw new Error("sink"); }, warn: () => {}, info: () => {}, log: () => {} },
    onError: (_error: Error) => { codes.push("sdk-error"); throw new Error("sink"); },
  };
  const App = createSessionApp(f.options, createThemeStore({ read: () => null, write: () => {} }), diagnostics);
  const ui = render(<App />);
  fireEvent(ui.getByTestId("animated-splash"), "layout");
  try {
    await ui.findByText("Something went wrong");
    expect(failures).toHaveBeenCalled(); expect(codes).toContain("sdk-error");
    expect(defaultLog).not.toHaveBeenCalled();
    const secureStore = jest.requireMock("expo-secure-store");
    expect(secureStore.getItem).not.toHaveBeenCalled();
    expect(secureStore.setItem).not.toHaveBeenCalled();
    expect(ui.queryByText("private request context must not be logged")).toBe(null);
  } finally { ui.unmount(); unsubscribe(); }
});

it("retains normal default diagnostic reporting when no fixture override is supplied", async () => {
  const f = fixture(); f.fail();
  const defaultLog = jest.spyOn(hyperviewLogger, "error").mockImplementation(() => {});
  const failures = jest.fn(), unsubscribe = subscribeToNetworkFailures(failures);
  const App = createSessionApp(f.options, createThemeStore({ read: () => null, write: () => {} }));
  const ui = render(<App />);
  fireEvent(ui.getByTestId("animated-splash"), "layout");
  try {
    await ui.findByText("Something went wrong");
    expect(failures).toHaveBeenCalled();
    expect(defaultLog).toHaveBeenCalledWith("request failed", expect.any(Error));
  } finally { ui.unmount(); unsubscribe(); }
});


it("never rebinds a previously published receiver to a newly authenticated account", async () => {
  const f = fixture(), ui = mount(f);
  try {
    await ui.findByText("Private A");
    await waitFor(() => expect(f.receivers.at(-1)).toEqual(expect.any(Function)));
    const oldReceiver = f.session.captureResources()!;
    fireEvent.press(ui.getByText("Sign in B"));
    await ui.findByText("Private B");
    await waitFor(() => expect(f.session.captureResources()).not.toBe(null));
    const newReceiver = f.session.captureResources()!;
    expect(newReceiver).not.toBe(oldReceiver);
    expect(f.receivers.at(-1)).toBe(newReceiver);
    expect(oldReceiver(["tasks"])).toBe(false);
    act(() => { expect(newReceiver(["tasks"])).toBe(true); });
    expect(ui.queryByText("Private A")).toBe(null);
    expect(f.http.mock.calls.filter(([, init]) => init?.method?.toUpperCase() === "POST")).toHaveLength(1);
  } finally { ui.unmount(); f.session.dispose(); }
});
