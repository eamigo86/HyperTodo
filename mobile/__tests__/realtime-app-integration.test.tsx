import "react-native-gesture-handler/jestSetup";
declare const __dirname: string; // Supplied by this Jest module, not the native App.
import React from "react";
import type Hyperview from "hyperview";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { Alert, AppState } from "react-native";
import { NavigationContainer } from "@react-navigation/native";
import { createStackNavigator } from "@react-navigation/stack";
import { createSessionApp } from "../App";
import { createThemeStore } from "../src/theme";
import { createAppSession, AppSessionSurface } from "../src/realtime/app-session";
import { SESSION_HEADERS as H } from "../src/realtime/session-protocol";
jest.mock("expo-splash-screen", () => ({
  preventAutoHideAsync: jest.fn(),
  hideAsync: jest.fn()
}));
jest.mock("lottie-react-native", () => {
  const React = jest.requireActual("react"),
    {
      View
    } = jest.requireActual("react-native");
  return {
    __esModule: true,
    default: React.forwardRef((props: any, ref: any) => {
      React.useImperativeHandle(ref, () => ({
        play: () => props.onAnimationFinish?.(false),
        reset: () => {}
      }));
      return <View {...props} />;
    })
  };
});
jest.mock("react-native-safe-area-context", () => jest.requireActual("react-native-safe-area-context/jest/mock").default);
jest.mock("react-native-webview", () => ({
  WebView: () => null
}));
jest.mock("expo-secure-store", () => ({
  getItem: () => null,
  setItem: () => {}
}));
const originalAppState = AppState.currentState;
beforeEach(() => {
  AppState.currentState = "active";
});
afterEach(() => {
  AppState.currentState = originalAppState;
});
const fs = jest.requireActual('fs');
const ORIGIN = "https://app.test",
  ENTRY = ORIGIN + "/hv/",
  A = "hvs1." + "A".repeat(43),
  B = "hvs1." + "B".repeat(43),
  TOKEN = "t".repeat(43),
  HV = "https://hyperview.org/hyperview",
  NS = "https://hypertodo.app/components";
const loginTransition = fs.readFileSync(jest.requireActual("path").resolve(__dirname, "../../backend/hyperview/fragments/login_transition.xml"), 'utf8').replace('{{ biometric_token }}', TOKEN);
function raw(body: string, binding: string, status = 200, outcome?: string) {
  const response = new Response(body, {
    status,
    headers: {
      [H.binding]: binding,
      ...(outcome ? {
        [H.outcome]: outcome
      } : {}),
      "Content-Type": "application/vnd.hyperview+xml",
      "X-HyperTodo-Theme": "dark"
    }
  });
  Object.defineProperty(response, "url", {
    value: ENTRY
  });
  return response;
}
function loginPanel(requestId?: string, message = "Login", clear = false) {
  return `<view xmlns="${HV}" id="login-panel" ${requestId ? `key="auth-panel-${requestId}"` : ""}>${clear ? '<behavior trigger="load" action="store-biometric-token" token="" once="true" immediate="true"/>' : ""}<text>${message}</text><form id="password-form"><text-field id="username" name="username" placeholder="Username" value="original"/><text-field id="password" name="password" placeholder="Password" value=""/><text-field hide="true" name="csrfmiddlewaretoken" value="own-csrf"/><switch name="enable_biometrics" value="on"/><view href="/hv/login/" verb="post" action="replace" target="login-panel"><text>Sign in</text></view></form><form id="biometric-form"><text-field id="biometric-token" name="biometric_token" value="" hide="true"/><view><behavior trigger="press" action="biometric-unlock" target="biometric-token" event-name="biometric-authenticated"/><behavior trigger="on-event" event-name="biometric-authenticated" href="/hv/biometric/login/" verb="post" action="replace" target="login-panel"/><text>Unlock</text></view></form></view>`;
}
function doc(id: string, authenticated: boolean) {
  return `<doc xmlns="${HV}" xmlns:app="${NS}"><screen><body><app:realtime refresh-href="/hv/" mode="notice" target="main" resources="tasks categories ui"><view id="main"><app:realtime-page request-id="${id}" page="1"/>${authenticated ? '<text>Account B</text>' : loginPanel()}</view></app:realtime></body></screen></doc>`;
}
function fixture() {
  let binding = A,
    authenticated = false,
    rootNavigation = false,
    language = "en";
  const save = jest.fn(async (_token: string) => {}),
    clear = jest.fn(async () => {}),
    read = jest.fn(async () => TOKEN);
  let tail = Promise.resolve();
  const storage = {
    enqueue: (job: (store: {
      save: typeof save;
      clear: typeof clear;
    }) => Promise<void>) => {
      const result = tail.then(() => job({
        save,
        clear
      }));
      tail = result.catch(() => {});
      return result;
    }
  };
  const theme = jest.fn(),
    notice = jest.fn(),
    stop = jest.fn();
  let status = 200;
  let override: ((url: string, init: RequestInit) => Promise<Response | undefined>) | undefined;
  let observedReady: boolean | undefined;
  const http = jest.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = input.toString();
    if (url.endsWith('/session-state/')) return raw(JSON.stringify({
      version: 1,
      authenticated,
      binding
    }), binding);
    if (override) {
      const response = await override(url, init ?? {});
      if (response) return response;
    }
    const id = new Headers(init?.headers).get('X-HyperTodo-Request-ID')!;
    if (rootNavigation && url === ENTRY) return raw(fs.readFileSync(jest.requireActual("path").resolve(__dirname, "../../backend/hyperview/screens/root.xml"), 'utf8').replace('{{ route_id }}', 'root-route').replace('{{ route_href }}', authenticated ? '/hv/dashboard/' : '/hv/login/'), binding);
    if ((init?.method ?? 'GET').toUpperCase() === 'POST') {
      if (status === 200) {
        binding = B;
        authenticated = true;
        return raw(loginTransition, B, 200, 'password-ok');
      }
      return status === 403 ? raw('<view xmlns="' + HV + '"><text>Private refusal</text></view>', A, 403) : raw(loginPanel(id, 'Rejected input'), A, status, 'password-invalid');
    }
    observedReady = session.snapshot().session.rootReady;
    return raw(doc(id, authenticated), binding);
  });
  const native = {
    platform: 'ios' as const,
    hasHardware: jest.fn(async () => false),
    isEnrolled: jest.fn(async () => false),
    supportedTypes: jest.fn(async () => []),
    readToken: read,
    unlock: jest.fn(async () => ({
      success: true
    })),
    pick: jest.fn(async () => ({
      canceled: true
    })),
    render: jest.fn(),
    save: jest.fn()
  };
  const options = {
    entrypointUrl: ENTRY,
    http: async (input: RequestInfo | URL, init?: RequestInit) => {
      const captured = language;
      const response = await http(input, init);
      response.headers.set("Content-Language", captured);
      return response;
    },
    credentials: {
      read,
      storage
    },
    native,
    onTheme: theme,
    onNotice: notice,
    stopStream: stop
  };
  const session = createAppSession(options);
  return {
    session,
    options,
    http,
    save,
    clear,
    read,
    native,
    theme,
    notice,
    stop,
    setLanguage: (value: string) => {
      language = value;
    },
    setOverride: (value: typeof override) => {
      override = value;
    },
    useRootNavigator: () => {
      rootNavigation = true;
    },
    setStatus: (next: number) => {
      status = next;
    },
    setBinding: (next: string, nextAuthenticated = authenticated) => {
      binding = next;
      authenticated = nextAuthenticated;
    },
    observedReady: () => observedReady
  };
}
const Stack = createStackNavigator();
function mount(session: ReturnType<typeof createAppSession>, components:React.ComponentProps<typeof Hyperview>["components"]=[]) {
  return render(<NavigationContainer><Stack.Navigator screenOptions={{
      animationEnabled: false
    }}><Stack.Screen name="app">{() => <AppSessionSurface session={session} hyperviewProps={{
          formatDate: () => undefined,components
        }} />}</Stack.Screen></Stack.Navigator></NavigationContainer>);
}
it("confirms before initial HTTP and marks startup ready only from the real focused layout", async () => {
  const f = fixture();
  expect(f.http).not.toHaveBeenCalled();
  expect(f.session.snapshot()).toBe(f.session.snapshot());
  const ui = mount(f.session);
  try {
    await ui.findByText('Login');
    await waitFor(() => expect(f.session.snapshot().session.rootReady).toBe(true));
    expect(f.http.mock.calls[0][0]).toBe(ORIGIN + '/hv/session-state/');
    expect(f.observedReady()).toBe(false);
    expect(f.session.snapshot().resources).toBe('connected');
    expect(f.theme).toHaveBeenCalledWith('dark');
  } finally {
    ui.unmount();
  }
});
it("submits actual password FormData once, awaits storage and resets the whole Root for B", async () => {
  const f = fixture(),
    ui = mount(f.session);
  try {
    await ui.findByText('Login');
    const epoch = f.session.gate.snapshot().epoch;
    fireEvent.changeText(ui.getByPlaceholderText('Username'), 'Ada é');
    fireEvent.changeText(ui.getByPlaceholderText('Password'), 'local draft');
    fireEvent.press(ui.getByText('Sign in'));
    await ui.findByText('Account B');
    const posts = f.http.mock.calls.filter(([, init]) => (init?.method ?? '').toUpperCase() === 'POST');
    expect(posts).toHaveLength(1);
    expect(new URLSearchParams(posts[0][1]!.body as string).get('username')).toBe('Ada é');
    expect(new URLSearchParams(posts[0][1]!.body as string).get('csrfmiddlewaretoken')).toBe('own-csrf');
    expect(f.save).toHaveBeenCalledTimes(1);
    expect(f.session.gate.snapshot().epoch).toBeGreaterThan(epoch);
    expect(ui.queryByPlaceholderText('Password')).toBeNull();
    await waitFor(() => expect(f.session.snapshot().session.rootReady).toBe(true));
  } finally {
    ui.unmount();
  }
});
it("preserves422 panel opt-in and submits its actual subsequent form", async () => {
  const f = fixture();
  f.setStatus(422);
  const ui = mount(f.session);
  try {
    await ui.findByText('Login');
    fireEvent.changeText(ui.getByPlaceholderText('Password'), 'entered');
    fireEvent.press(ui.getByText('Sign in'));
    await ui.findByText('Rejected input');
    expect(f.save).not.toHaveBeenCalled();
    expect(f.clear).not.toHaveBeenCalled();
    f.setStatus(200);
    fireEvent.changeText(ui.getByPlaceholderText('Username'), 'second attempt');
    fireEvent.press(ui.getByText('Sign in'));
    await ui.findByText('Account B');
    const posts = f.http.mock.calls.filter(([, init]) => (init?.method ?? '').toUpperCase() === 'POST');
    expect(posts).toHaveLength(2);
    expect(new URLSearchParams(posts[1][1]!.body as string).get('enable_biometrics')).toBe('on');
    expect(new URLSearchParams(posts[1][1]!.body as string).get('username')).toBe('second attempt');
  } finally {
    ui.unmount();
  }
});
it("keeps the same Root and entered draft through a confirmed pause and foreground", async () => {
  const f = fixture(),
    ui = mount(f.session);
  try {
    await ui.findByText('Login');
    fireEvent.changeText(ui.getByPlaceholderText('Password'), 'keep this draft');
    const epoch = f.session.gate.snapshot().epoch;
    await act(async () => f.session.pause());
    expect(ui.getByLabelText('Session protection')).toBeTruthy();
    expect(f.session.gate.snapshot()).toMatchObject({
      epoch,
      retainedPaused: true
    });
    await act(async () => {
      await f.session.foreground();
    });
    expect(ui.getByPlaceholderText('Password').props.value).toBe('keep this draft');
    expect(f.session.gate.snapshot()).toMatchObject({
      epoch,
      retainedPaused: false
    });
    expect(f.http.mock.calls.filter(([url]) => url === ENTRY)).toHaveLength(1);
    expect(f.stop).toHaveBeenCalled();
  } finally {
    ui.unmount();
  }
});
it("shields an unexpected foreground identity without fetching it or replaying a POST", async () => {
  const f = fixture(),
    ui = mount(f.session);
  try {
    await ui.findByText('Login');
    fireEvent.changeText(ui.getByPlaceholderText('Password'), 'private A');
    await act(async () => f.session.pause());
    f.setBinding(B);
    await act(async () => {
      await f.session.foreground();
    });
    expect(ui.getByLabelText('Session protection')).toBeTruthy();
    expect(ui.queryByPlaceholderText('Password')).toBeNull();
    expect(f.session.snapshot().session.identity).toBeNull();
    expect(f.http.mock.calls.filter(([url]) => url === ENTRY)).toHaveLength(1);
    expect(f.http.mock.calls.filter(([, init]) => (init?.method ?? '').toUpperCase() === 'POST')).toHaveLength(0);
  } finally {
    ui.unmount();
  }
});
it("presents403 as a safe notice and retains entered fields without a false XML ACK", async () => {
  const f = fixture();
  f.setStatus(403);
  const ui = mount(f.session);
  try {
    await ui.findByText('Login');
    fireEvent.changeText(ui.getByPlaceholderText('Password'), 'retain403');
    fireEvent.press(ui.getByText('Sign in'));
    await ui.findByText('Your session could not verify this request. Your changes are still here. Try again.');
    expect(ui.getByPlaceholderText('Password').props.value).toBe('retain403');
    expect(ui.queryByText('Private refusal')).toBeNull();
    await waitFor(() => expect(f.session.gate.snapshot().lastTerminal).toMatchObject({
      outcome: 'no-document',
      reason: 'auth-refused'
    }));
    expect(f.save).not.toHaveBeenCalled();
    expect(f.clear).not.toHaveBeenCalled();
  } finally {
    ui.unmount();
  }
});
it("runs the same actual App shell and SDK with injected origin, credentials and theme", async () => {
  const f = fixture();
  f.useRootNavigator();
  const themeRead = jest.fn(() => "light"),
    themeWrite = jest.fn();
  const theme = createThemeStore({
    read: themeRead,
    write: themeWrite
  });
  const FixtureApp = createSessionApp(f.options, theme);
  const ui = render(<FixtureApp />);
  try {
    fireEvent(ui.getByTestId("animated-splash"), "layout");
    await ui.findByText("Login");
    expect(ui.getByLabelText("HyperTodo safe area")).toBeTruthy();
    expect(themeRead).toHaveBeenCalledTimes(1);
    expect(themeWrite).toHaveBeenCalledWith("dark");
    fireEvent.press(ui.getByText("Sign in"));
    await ui.findByText("Account B");
    expect(f.save).toHaveBeenCalledTimes(1);
  } finally {
    ui.unmount();
  }
});
it.each([401, 429])("delivers a real biometric %s panel and never repeats or invents its credential effect", async status => {
  const f = fixture();
  f.setOverride(async (url, init) => {
    if (!url.endsWith('/biometric/login/')) return undefined;
    expect(new URLSearchParams(init.body as string).get('biometric_token')).toBe(TOKEN);
    return raw(loginPanel(new Headers(init.headers).get('X-HyperTodo-Request-ID')!, 'Biometric retry', status === 401), A, status, status === 401 ? 'biometric-invalid' : 'biometric-throttled');
  });
  const ui = mount(f.session);
  try {
    await ui.findByText('Login');
    fireEvent.press(ui.getByText('Unlock'));
    await ui.findByText('Biometric retry');
    await waitFor(() => expect(f.session.gate.snapshot().lastTerminal?.reason).toBe('auth-panel-layout'));
    expect(f.native.unlock).toHaveBeenCalledTimes(1);
    expect(f.read).toHaveBeenCalledTimes(1);
    expect(f.clear).toHaveBeenCalledTimes(status === 401 ? 1 : 0);
    expect(f.save).not.toHaveBeenCalled();
    expect(f.http.mock.calls.filter(([url]) => url.toString().endsWith('/biometric/login/'))).toHaveLength(1);
  } finally {
    ui.unmount();
  }
});
it("executes Settings clear only from the owned successful source and does not wipe on an initial empty-token node", async () => {
  const f = fixture();
  let settings = false;
  f.setOverride(async (url, init) => {
    const id = new Headers(init.headers).get('X-HyperTodo-Request-ID')!;
    if (url.endsWith('/settings/') && init.method === 'POST') {
      settings = true;
      return raw(`<view xmlns="${HV}" xmlns:app="${NS}" id="settings-form-panel"><app:realtime-page request-id="${id}" page="1"/><behavior trigger="load" action="store-biometric-token" token="" once="true" immediate="true"/><text>Settings saved</text></view>`, A);
    }
    if (url === ENTRY) return raw(doc(id, false).replace(loginPanel(), `<view id="settings-form-panel"><behavior trigger="load" action="store-biometric-token" token="" once="true" immediate="true"/><text>Settings draft</text></view><form><text-field name="csrfmiddlewaretoken" value="own-csrf" hide="true"/><view href="/hv/settings/" verb="post" action="replace" target="settings-form-panel"><text>Save settings</text></view></form>`), A);
    return undefined;
  });
  const ui = mount(f.session);
  try {
    await ui.findByText('Settings draft');
    expect(f.clear).not.toHaveBeenCalled();
    fireEvent.press(ui.getByText('Save settings'));
    await ui.findByText('Settings saved');
    await waitFor(() => expect(f.clear).toHaveBeenCalledTimes(1));
    expect(settings).toBe(true);
    expect(f.save).not.toHaveBeenCalled();
  } finally {
    ui.unmount();
  }
});

it.each(['accept','logout','refused'] as const)('defers real Settings credential effects behind newer form edits without POST replay: %s',async outcome=>{
 const f=fixture();f.setBinding(A,true);let release!:(response:Response)=>void,postId='',signedOut=false;
 const pending=new Promise<Response>(resolve=>{release=resolve;}),dialog=jest.spyOn(Alert,'alert').mockImplementation(()=>{});
 f.setOverride(async(url,init)=>{
  const id=new Headers(init.headers).get('X-HyperTodo-Request-ID')!;
  if(url.endsWith('/settings/')&&init.method==='POST'){postId=id;return pending;}
  if(url.endsWith('/logout/')&&init.method==='POST'){
   signedOut=true;f.setBinding(B,false);
   return raw(fs.readFileSync(jest.requireActual('path').resolve(__dirname,'../../backend/hyperview/fragments/logout_transition.xml'),'utf8'),B,200,'logout-ok');
  }
  if(url===ENTRY&&!signedOut)return raw(doc(id,true).replace('mode="notice"','mode="form"').replace('<text>Account B</text>',`<view id="settings-form-panel"><form id="settings-form"><text-field name="display_name" placeholder="Display name" value="initial"/><text-field hide="true" name="csrfmiddlewaretoken" value="own-csrf"/><view href="/hv/settings/" verb="post" action="replace" target="settings-form-panel"><text>Save settings draft</text></view></form></view><view id="logout-panel"><form><text-field hide="true" name="csrfmiddlewaretoken" value="own-csrf"/><view href="/hv/logout/" verb="post" action="replace" target="logout-panel"><text>Sign out now</text></view></form></view>`),A);
  return undefined;
 });
 const ui=mount(f.session);
 try{
  await ui.findByPlaceholderText('Display name');fireEvent.changeText(ui.getByPlaceholderText('Display name'),'submitted');
  fireEvent.press(ui.getByText('Save settings draft'));await waitFor(()=>expect(postId).not.toBe(''));
  fireEvent.changeText(ui.getByPlaceholderText('Display name'),'new unsaved name');
  await act(async()=>release(raw(`<view xmlns="${HV}" xmlns:app="${NS}" id="settings-form-panel"><app:realtime-page request-id="${postId}" page="1"/><behavior trigger="load" action="store-biometric-token" token="" once="true" immediate="true"/><text>Settings response</text></view>`,A,outcome==='refused'?422:200)));
  await ui.findByText('Your newer edits are still here. Discard them to show the server response.');
  expect(ui.getByPlaceholderText('Display name').props.value).toBe('new unsaved name');expect(f.clear).not.toHaveBeenCalled();expect(ui.queryByText('Settings response')).toBeNull();
  if(outcome==='logout'){
   const epoch=f.session.gate.snapshot().epoch;fireEvent.press(ui.getByText('Sign out now'));await ui.findByText('Login');
   expect(f.session.gate.snapshot().epoch).toBeGreaterThan(epoch);expect(f.clear).not.toHaveBeenCalled();expect(ui.queryByText('Settings response')).toBeNull();
  }else{
   fireEvent.press(ui.getByRole('button',{name:'Update'}));expect(dialog).toHaveBeenCalledTimes(1);expect(f.clear).not.toHaveBeenCalled();
   await act(async()=>dialog.mock.calls[0][2]!.find(button=>button.style==='destructive')!.onPress!());await ui.findByText('Settings response');
   await waitFor(()=>expect(f.session.gate.snapshot().operations).toBe(0));expect(f.clear).toHaveBeenCalledTimes(outcome==='accept'?1:0);
  }
  const posts=f.http.mock.calls.filter(([url,init])=>String(url).endsWith('/settings/')&&init?.method==='POST');
  expect(posts).toHaveLength(1);expect(new URLSearchParams(posts[0][1]?.body as string).get('csrfmiddlewaretoken')).toBe('own-csrf');
  expect(f.save).not.toHaveBeenCalled();
 }finally{dialog.mockRestore();ui.unmount();}
});
it("retains a successful B response in background and publishes only after confirmations and awaited storage", async () => {
  const f = fixture();
  let release!: () => void;
  const deferred = new Promise<void>(resolve => {
    release = resolve;
  });
  f.setOverride(async (url, init) => {
    if (init.method !== 'POST') return undefined;
    await deferred;
    f.setBinding(B, true);
    return raw(loginTransition, B, 200, 'password-ok');
  });
  const ui = mount(f.session);
  try {
    await ui.findByText('Login');
    fireEvent.press(ui.getByText('Sign in'));
    await waitFor(() => expect(f.http.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true));
    await act(async () => f.session.pause());
    await act(async () => {
      release();
    });
    expect(f.save).not.toHaveBeenCalled();
    expect(f.session.snapshot().session.identity?.binding).toBe(A);
    expect(ui.queryByText('Account B')).toBeNull();
    // The observation fixture must agree with the successful response's B.
    f.setOverride(undefined);
    await act(async () => {
      await f.session.foreground();
    });
    expect(f.save).toHaveBeenCalledTimes(1);
    await ui.findByText("Account B");
    expect(f.session.snapshot().session.identity?.binding).toBe(B);
    expect(f.http.mock.calls.filter(([url]) => url.toString().endsWith("/session-state/"))).toHaveLength(3);
  } finally {
    ui.unmount();
  }
});
it("logout rotates the whole Root without deleting device enrollment", async () => {
  const f = fixture();
  let signedOut = false;
  f.setBinding(A, true);
  f.setOverride(async (url, init) => {
    const id = new Headers(init.headers).get('X-HyperTodo-Request-ID')!;
    if (url.endsWith('/logout/') && init.method === 'POST') {
      signedOut = true;
      f.setBinding(B, false);
      return raw(fs.readFileSync(jest.requireActual("path").resolve(__dirname, "../../backend/hyperview/fragments/logout_transition.xml"), 'utf8'), B, 200, 'logout-ok');
    }
    if (url === ENTRY && !signedOut) return raw(doc(id, true).replace('<text>Account B</text>', '<view id="logout-panel"><form><text-field name="csrfmiddlewaretoken" value="csrf" hide="true"/><view href="/hv/logout/" verb="post" action="replace" target="logout-panel"><text>Sign out</text></view></form></view>'), A);
    return undefined;
  });
  const ui = mount(f.session);
  try {
    await ui.findByText('Sign out');
    const epoch = f.session.gate.snapshot().epoch;
    fireEvent.press(ui.getByText('Sign out'));
    await ui.findByText('Login');
    expect(f.session.gate.snapshot().epoch).toBeGreaterThan(epoch);
    expect(f.clear).not.toHaveBeenCalled();
    expect(f.save).not.toHaveBeenCalled();
    expect(f.session.snapshot().session.identity).toMatchObject({
      binding: B,
      authenticated: false
    });
  } finally {
    ui.unmount();
  }
});
it("does not let a late native unlock from removed A submit or mutate newly confirmed B", async () => {
  const f = fixture();
  let finish!: (value: {
    success: boolean;
  }) => void;
  f.native.unlock.mockImplementationOnce(() => new Promise(resolve => {
    finish = resolve;
  }));
  const ui = mount(f.session);
  try {
    await ui.findByText('Login');
    fireEvent.press(ui.getByText('Unlock'));
    await waitFor(() => expect(f.native.unlock).toHaveBeenCalledTimes(1));
    fireEvent.press(ui.getByText('Sign in'));
    await ui.findByText('Account B');
    await act(async () => finish({
      success: true
    }));
    expect(f.read).not.toHaveBeenCalled();
    expect(f.http.mock.calls.filter(([url]) => url.toString().endsWith('/biometric/login/'))).toHaveLength(0);
    expect(f.notice).not.toHaveBeenCalled();
    expect(f.save).toHaveBeenCalledTimes(1);
  } finally {
    ui.unmount();
  }
});
it("uses the owned server language for native protection text without replacing its draft or Root", async () => {
  const f = fixture();
  f.setLanguage('es');
  const ui = mount(f.session);
  try {
    await ui.findByText('Login');
    fireEvent.changeText(ui.getByPlaceholderText('Password'), 'borrador');
    const epoch = f.session.gate.snapshot().epoch;
    await act(async () => f.session.pause());
    expect(ui.getByLabelText('Protección de sesión')).toBeTruthy();
    expect(ui.getByText('Sesión en pausa')).toBeTruthy();
    await act(async () => {
      await f.session.foreground();
    });
    f.setLanguage('en');
    await act(async () => {
      await f.session.supervisor.request('/hv/tasks/');
    });
    await act(async () => f.session.pause());
    expect(ui.getByLabelText('Session protection')).toBeTruthy();
    expect(ui.getByPlaceholderText('Password', {
      includeHiddenElements: true
    }).props.value).toBe('borrador');
    expect(f.session.gate.snapshot().epoch).toBe(epoch);
  } finally {
    ui.unmount();
  }
});
it.each(['password', 'biometric'])('offers explicit neutral recovery after mismatch and a source-owned %s login', async method => {
  const f = fixture(),
    ui = mount(f.session);
  try {
    await ui.findByText('Login');
    const owner = f.session.supervisor;
    await act(async () => f.session.pause());
    f.setBinding(B, true);
    await act(async () => {
      await f.session.foreground();
    });
    expect(f.session.snapshot().session.identity).toBeNull();
    const before = f.http.mock.calls.length;
    f.setOverride(async (url, init) => {
      if (url === ORIGIN + '/hv/biometric/login/') {
        f.setBinding(B, true);
        return raw(loginTransition, B, 200, 'biometric-ok');
      }
      if (url === ORIGIN + '/hv/recovery/') return raw(`<doc xmlns="${HV}"><navigator id="recovery-root" type="stack"><nav-route id="public-login" href="/hv/recovery/?screen=login" selected="true"/></navigator></doc>`, B);
      if (url === ORIGIN + '/hv/recovery/?screen=login') return raw(doc(new Headers(init.headers).get('X-HyperTodo-Request-ID')!, false).replace('<text>Login</text>', '<text>Neutral Login</text>'), B);
      return undefined;
    });
    fireEvent.press(ui.getByRole('button', {
      name: 'Sign in'
    }));
    await ui.findByText('Neutral Login');
    expect(f.session.supervisor).toBe(owner);
    expect(f.session.snapshot().session.identity).toBeNull();
    expect(f.http.mock.calls.slice(before).filter(([url]) => !url.toString().endsWith('/session-state/')).map(([url]) => url)).toEqual([ORIGIN + '/hv/recovery/', ORIGIN + '/hv/recovery/?screen=login']);
    fireEvent.changeText(ui.getByPlaceholderText('Username'), 'deliberate');
    fireEvent.press(ui.getByText(method === 'password' ? 'Sign in' : 'Unlock'));
    await ui.findByText('Account B');
    expect(f.save).toHaveBeenCalledTimes(1);
    expect(f.session.snapshot().session.identity?.binding).toBe(B);
  } finally {
    ui.unmount();
  }
});
it('retains the actual App navigation and draft through hints, theme and same-identity lifecycle notifications', async () => {
  const add = AppState.addEventListener,
    spy = jest.fn((...args: Parameters<typeof add>) => add(...args)),
    f = fixture();
  AppState.addEventListener = spy;
  f.useRootNavigator();
  const theme = createThemeStore({
    read: () => "light",
    write: () => {}
  });
  const observations = jest.fn(), receiver = jest.fn();
  const FixtureApp = createSessionApp({ ...f.options, onGateObservation: observations, onResourceReceiver: receiver }, theme);
  const ui = render(<FixtureApp />);
  try {
    fireEvent(ui.getByTestId('animated-splash'), 'layout');
    await ui.findByText('Login');
    const change = (state: 'inactive' | 'active') => {
      for (const [event, handler] of spy.mock.calls) if (event === 'change') handler(state);
    };
    fireEvent.changeText(ui.getByPlaceholderText('Password'), 'native event draft');
    const field = ui.getByPlaceholderText('Password');
    const observed = observations.mock.calls.length;
    expect(theme.getSnapshot()).toBe('dark'); // The accepted HTTP header superseded persisted light.
    await act(async () => {
      expect(receiver.mock.calls.at(-1)?.[0](['tasks'])).toBe(true);
      theme.publish('light');
    });
    expect(theme.getSnapshot()).toBe('light');
    await ui.findByText('There may be changes');
    expect(ui.getByPlaceholderText('Password')).toBe(field);
    await act(async () => change('inactive'));
    expect(ui.getByLabelText('Session protection')).toBeTruthy();
    await act(async () => change('active'));
    await waitFor(() => expect(ui.queryByLabelText('Session protection')).toBeNull());
    expect(ui.getByPlaceholderText('Password').props.value).toBe('native event draft');
    expect(ui.getByPlaceholderText('Password')).toBe(field);
    expect(f.http.mock.calls.filter(([url]) => url === ENTRY)).toHaveLength(1);
    expect(f.http.mock.calls.filter(([url, init]) => !url.toString().endsWith('/session-state/') && (init?.method ?? 'GET') === 'GET')).toHaveLength(2);
    expect(f.http.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
    expect(observations.mock.calls).toHaveLength(observed);
  } finally {
    ui.unmount();
    AppState.addEventListener = add;
  }
});
it('does not show a private Root when the App initially mounts inactive', async () => {
  const before = AppState.currentState;
  AppState.currentState = 'background';
  const f = fixture();
  f.useRootNavigator();
  const FixtureApp = createSessionApp(f.options, createThemeStore({
    read: () => "light",
    write: () => {}
  }));
  const ui = render(<FixtureApp />);
  try {
    fireEvent(ui.getByTestId('animated-splash'), 'layout');
    await waitFor(() => expect(f.http.mock.calls.length).toBeGreaterThan(0));
    await act(async () => {
      await Promise.resolve();
    });
    expect(ui.queryByText('Login')).toBeNull();
    expect(ui.getByLabelText('Session protection')).toBeTruthy();
    expect(f.http.mock.calls.filter(([url]) => url === ENTRY)).toHaveLength(0);
  } finally {
    ui.unmount();
    AppState.currentState = before;
  }
});
it('routes a real owned notify-resources behavior to its captured dependency gate and repaints language without losing a draft', async () => {
  const f = fixture();
  f.setLanguage('es');
  f.setOverride(async (url, init) => url === ENTRY ? raw(doc(new Headers(init.headers).get('X-HyperTodo-Request-ID')!, false).replace('</app:realtime>', '<view><behavior trigger="press" action="notify-resources" resources="tasks"/><text>Resource hint</text></view></app:realtime>'), A) : undefined);
  const ui = mount(f.session);
  try {
    await ui.findByText('Login');
    fireEvent.changeText(ui.getByPlaceholderText('Password'), 'resource draft');
    const epoch = f.session.gate.snapshot().epoch;
    await act(async()=>fireEvent.press(ui.getByText('Resource hint')));
    expect(ui.queryByText('Puede haber cambios')).toBeNull();
    expect(f.session.gate.snapshot().routes[0].notice).toBe(true);
    expect(f.http.mock.calls.filter(([url]) => url === ENTRY)).toHaveLength(1);
    act(()=>f.session.captureResources()!(['tasks']));
    await ui.findByText('Puede haber cambios');
    f.setLanguage('en');
    await act(async () => {
      await f.session.supervisor.request('/hv/tasks/');
    });
    await ui.findByText('There may be changes');
    expect(ui.getByPlaceholderText('Password').props.value).toBe('resource draft');
    expect(f.session.gate.snapshot().epoch).toBe(epoch);
  } finally {
    ui.unmount();
  }
});
it('exposes a ready-only captured resource receiver that an old connection cannot reuse for B', async () => {
  const f = fixture();
  expect(f.session.captureResources()).toBeNull();
  const ui = mount(f.session);
  try {
    await ui.findByText('Login');
    await waitFor(() => expect(f.session.snapshot().session.rootReady).toBe(true));
    const receiver = f.session.captureResources()!;
    expect(receiver).toEqual(expect.any(Function));
    fireEvent.press(ui.getByText('Sign in'));
    await ui.findByText('Account B');
    let accepted = true;
    act(() => {
      accepted = receiver(['tasks']);
    });
    expect(accepted).toBe(false);
    expect(ui.queryByText('There may be changes')).toBeNull();
  } finally {
    ui.unmount();
  }
});


it('retires a rejected Parser form snapshot so a subsequent corrected auth action can progress', async () => {
  const originalFormData = globalThis.FormData;
  globalThis.FormData = jest.requireActual("react-native/Libraries/Network/FormData").default;
  const f = fixture();
  let invalid = true;
  const Field = Object.assign(() => null, {
    namespaceURI: NS,
    localName: 'invalid-form-field',
    getFormInputValues: () => [['upload', invalid ? {
      uri: 'file://synthetic',
      name: 'synthetic',
      type: 'image/png'
    } as unknown as string : 'fixed']] as [string, string][]
  });
  f.setOverride(async (url, init) => url === ENTRY ? raw(doc(new Headers(init.headers).get('X-HyperTodo-Request-ID')!, false).replace('<form id="password-form">', '<form id="password-form"><app:invalid-form-field/>'), A) : undefined);
  const ui = mount(f.session, [Field]);
  try {
    await ui.findByText('Login');
    fireEvent.press(ui.getByText('Sign in'));
    await waitFor(() => expect(f.session.gate.snapshot().lastTerminal?.reason).toBe('request-error'));
    expect(f.http.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
    invalid = false;
    f.setOverride(undefined);
    fireEvent.press(ui.getByText('Sign in'));
    await ui.findByText('Account B');
    expect(f.http.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
  } finally {
    ui.unmount();
    globalThis.FormData = originalFormData;
  }
});

/** Own HTTP outcomes are controlled; all retained rendering and layout use real Hyperview. */
async function twoCycleForegroundControl(language: string, heading?: string) {
  const f = fixture();
  f.setBinding(B, true);
  f.setLanguage(language);
  let release!: (response: Response) => void;
  const heldResponse = new Promise<Response>(resolve => { release = resolve; });
  f.setOverride(async (url, init) => {
    if (url.endsWith('/tasks/fragment/')) return heldResponse;
    const requestId = new Headers(init.headers).get('X-HyperTodo-Request-ID')!;
    return raw(doc(requestId, true).replace('<text>Account B</text>',
      '<text>Account B</text><form><text-field name="draft" placeholder="Task draft" value="original"/></form>' +
      '<view id="rows"><text>Rows</text></view>' +
      '<view href="/hv/tasks/fragment/" action="append" target="rows"><text>Load fragment</text></view>'), B);
  });
  const ui = mount(f.session);
  try {
    await ui.findByText('Account B');
    await waitFor(() => expect(f.session.snapshot().session.rootReady).toBe(true));
    const identity = f.session.snapshot().session.identity;
    const epoch = f.session.gate.snapshot().epoch;
    fireEvent.changeText(ui.getByPlaceholderText('Task draft'), 'retained task draft');
    await act(async () => { expect(f.session.captureResources()?.(['tasks'])).toBe(true); });
    fireEvent.press(ui.getByText('Load fragment'));
    await waitFor(() => expect(f.http.mock.calls.some(([url]) => url.toString().endsWith('/tasks/fragment/'))).toBe(true));
    const fragmentInit = f.http.mock.calls.find(([url]) => url.toString().endsWith('/tasks/fragment/'))![1];
    const id = new Headers(fragmentInit?.headers).get('X-HyperTodo-Request-ID');
    await act(async () => {
      f.session.pause();
      release(raw(`<view xmlns="${HV}" xmlns:app="${NS}"><app:realtime-page request-id="${id}" page="1"/><text>Appended fragment</text></view>`, B));
      await f.session.foreground();
    });
    await ui.findByText('Appended fragment');
    expect(f.session.snapshot().session.identity).toBe(identity);
    expect(ui.getByPlaceholderText('Task draft').props.value).toBe('retained task draft');

    const normal = f.http.getMockImplementation()!;
    let failConfirmation = true;
    let failedAttempts = 0;
    let releaseRetry!: () => void;
    const retryBarrier = new Promise<void>(resolve => { releaseRetry = resolve; });
    f.http.mockImplementation(async (input, init) => {
      if (input.toString().endsWith('/session-state/') && failConfirmation) {
        failedAttempts++;
        throw new Error('controlled confirmation failure');
      }
      if (heading && input.toString().endsWith('/session-state/')) await retryBarrier;
      return normal(input, init);
    });
    act(() => { f.session.pause(); });
    expect(ui.getByText(language.startsWith('es') ? 'Sesión en pausa' : 'Session paused')).toBeTruthy();
    await act(async () => { await f.session.foreground(); });
    expect(failedAttempts).toBe(3);
    expect(f.session.snapshot().session).toMatchObject({ availability: 'uncertain', reason: 'network-uncertain' });
    expect(f.session.snapshot().session.identity).toBe(identity);
    expect(f.session.gate.snapshot().epoch).toBe(epoch);
    expect(ui.getByLabelText(language.startsWith('es') ? 'Protección de sesión' : 'Session protection')).toBeTruthy();
    if (heading) {
      expect(ui.getByText(heading)).toBeTruthy();
      expect(ui.queryByText(language.startsWith('es') ? 'Confirmando tu sesión' : 'Confirming your session')).toBeNull();
    }
    expect(ui.queryByPlaceholderText('Password')).toBeNull();
    const docsBeforeRetry = f.http.mock.calls.filter(([url]) => url === ENTRY).length;
    failConfirmation = false;
    await act(async () => {
      fireEvent.press(ui.getByLabelText(language.startsWith('es') ? 'Volver a comprobar la sesión' : 'Retry session confirmation'));
    });
    if (heading) {
      // Retrying retains the last failure message; it does not invent a busy state.
      expect(ui.getByText(heading)).toBeTruthy();
      await act(async () => { releaseRetry(); });
    }
    await waitFor(() => expect(f.session.snapshot().session.availability).toBe('foreground'));
    expect(f.session.snapshot().session.identity).toBe(identity);
    expect(f.session.gate.snapshot().epoch).toBe(epoch);
    expect(ui.getByPlaceholderText('Task draft').props.value).toBe('retained task draft');
    expect(ui.getByText('Appended fragment')).toBeTruthy();
    expect(f.http.mock.calls.filter(([url]) => url === ENTRY)).toHaveLength(docsBeforeRetry);
    expect(f.http.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
  } finally {
    ui.unmount();
  }
}

it('retains identity and draft across held work, two lifecycle cycles and explicit confirmation retry', async () => {
  await twoCycleForegroundControl('en');
}, 15000);


it.each([
  ['en', 'We could not confirm your session'],
  ['es-AR', 'No pudimos confirmar tu sesión']
])('shows an accurate %s heading after confirmation retries finish', async (language, heading) => {
  await twoCycleForegroundControl(language, heading);
}, 15000);

it('does not label the initial unconfirmed bootstrap as a failed attempt', async () => {
  const f = fixture();
  let release!: (response: Response) => void;
  const response = new Promise<Response>(resolve => { release = resolve; });
  f.http.mockImplementationOnce(async () => response);
  const ui = mount(f.session);
  try {
    expect(f.session.snapshot().session).toMatchObject({ availability: 'uncertain', reason: 'bootstrap-required' });
    expect(ui.getByText('Confirming your session')).toBeTruthy();
    expect(ui.queryByText('We could not confirm your session')).toBeNull();
    await act(async () => {
      release(raw(JSON.stringify({ version: 1, authenticated: false, binding: A }), A));
    });
    await ui.findByText('Login');
  } finally {
    ui.unmount();
  }
});

it('preserves a real root navigator through three rejected panels followed by accepted login', async () => {
  const f = fixture();
  f.useRootNavigator();
  f.setStatus(422);
  const ActualApp = createSessionApp(f.options, createThemeStore({ read: () => 'light', write: () => {} }));
  const ui = render(<ActualApp />);
  try {
    fireEvent(ui.getByTestId('animated-splash'), 'layout');
    await ui.findByText('Login');
    for (let attempt = 0; attempt < 3; attempt += 1) {
      fireEvent.changeText(ui.getByPlaceholderText('Password'), `rejected-${attempt}`);
      fireEvent.press(ui.getByText('Sign in'));
      await waitFor(() => expect(f.http.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(attempt + 1));
      await ui.findByText('Rejected input');
      await waitFor(() => expect(ui.getByPlaceholderText('Password').props.value).toBe(''));
    }
    f.setStatus(200);
    fireEvent.changeText(ui.getByPlaceholderText('Password'), 'accepted synthetic password');
    fireEvent.press(ui.getByText('Sign in'));
    await ui.findByText('Account B');
    expect(f.save).toHaveBeenCalledTimes(1);
    expect(f.http.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(4);
  } finally {
    ui.unmount();
  }
});

it.each(['onBlur', 'onFocus', 'onChangeText'])('ignores a retired text-field %s after auth panel replacement and preserves the next login root', async handler => {
  const f = fixture();
  f.useRootNavigator();
  f.setStatus(422);
  const ActualApp = createSessionApp(f.options, createThemeStore({ read: () => 'light', write: () => {} }));
  const ui = render(<ActualApp />);
  try {
    fireEvent(ui.getByTestId('animated-splash'), 'layout');
    await ui.findByText('Login');
    // Public native handler captured before the response removes its field.
    const retiredHandler = ui.getByPlaceholderText('Password').props[handler];
    fireEvent.press(ui.getByText('Sign in'));
    await ui.findByText('Rejected input');
    await act(async () => retiredHandler('stale value must not reach the same-id current field'));
    expect(ui.getByText('Rejected input')).toBeTruthy();
    expect(ui.getByPlaceholderText('Password').props.value).toBe('');
    f.setStatus(200);
    fireEvent.press(ui.getByText('Sign in'));
    await ui.findByText('Account B');
    expect(f.save).toHaveBeenCalledTimes(1);
  } finally {
    ui.unmount();
  }
});

it('preserves current native focus, batched edits, blur and form submission after a panel replacement', async () => {
  const f = fixture();
  f.useRootNavigator();
  f.setStatus(422);
  const ActualApp = createSessionApp(f.options, createThemeStore({ read: () => 'light', write: () => {} }));
  const ui = render(<ActualApp />);
  try {
    fireEvent(ui.getByTestId('animated-splash'), 'layout');
    await ui.findByText('Login');
    fireEvent.press(ui.getByText('Sign in'));
    await ui.findByText('Rejected input');
    fireEvent(ui.getByPlaceholderText('Password'), 'focus');
    const onChange = ui.getByPlaceholderText('Password').props.onChangeText;
    await act(async () => { onChange('current'); onChange('current complete'); });
    expect(ui.getByPlaceholderText('Password').props.value).toBe('current complete');
    fireEvent(ui.getByPlaceholderText('Password'), 'blur');
    expect(ui.getByPlaceholderText('Password').props.value).toBe('current complete');
    f.setStatus(200);
    fireEvent.press(ui.getByText('Sign in'));
    await ui.findByText('Account B');
    const posts = f.http.mock.calls.filter(([, init]) => init?.method === 'POST');
    expect(posts).toHaveLength(2);
    expect(new URLSearchParams(posts[1][1]!.body as string).get('password')).toBe('current complete');
    expect(f.save).toHaveBeenCalledTimes(1);
  } finally {
    ui.unmount();
  }
});

it('loads the authenticated root destination instead of retaining the previous login URL', async () => {
  const f = fixture();
  f.useRootNavigator();
  let acceptedPost = false;
  f.setOverride(async (url, init) => {
    if (init.method === 'POST') { acceptedPost = true; return undefined; }
    if (url === ORIGIN + '/hv/login/') {
      const id = new Headers(init.headers).get('X-HyperTodo-Request-ID')!;
      // Match the actual backend: GET login is a form even for an authenticated
      // session. A stale route must not be hidden by returning dashboard here.
      return raw(doc(id, false), acceptedPost ? B : A);
    }
    return undefined;
  });
  const ActualApp = createSessionApp(f.options, createThemeStore({ read: () => 'light', write: () => {} }));
  const ui = render(<ActualApp />);
  try {
    fireEvent(ui.getByTestId('animated-splash'), 'layout');
    await ui.findByText('Login');
    fireEvent.press(ui.getByText('Sign in'));
    await waitFor(() => expect(f.save).toHaveBeenCalledTimes(1));
    await ui.findByText('Account B');
    expect(f.http.mock.calls.filter(([url, init]) => url === ORIGIN + '/hv/login/' && (init?.method ?? 'GET') === 'GET')).toHaveLength(1);
    expect(f.http.mock.calls.filter(([url, init]) => url === ORIGIN + '/hv/dashboard/' && (init?.method ?? 'GET') === 'GET')).toHaveLength(1);
    expect(ui.queryByText('Login')).toBeNull();
  } finally {
    ui.unmount();
  }
});

it('leaves the actual neutral recovery navigator for B after a mutated A task route is revoked', async () => {
  const f = fixture();
  f.useRootNavigator();
  f.setBinding('hvs1.' + 'D'.repeat(43), false);
  const C = 'hvs1.' + 'C'.repeat(43);
  let acceptedB = false, mutated = false, logins = 0;
  const tasks = ORIGIN + '/hv/tasks/?status=active';
  const toggle = ORIGIN + '/hv/tasks/00000000-0000-0000-0000-000000000001/toggle/';
  const rootTemplate = fs.readFileSync(jest.requireActual("path").resolve(__dirname, "../../backend/hyperview/screens/root.xml"), 'utf8');
  f.setOverride(async (url, init) => {
    const id = new Headers(init.headers).get('X-HyperTodo-Request-ID')!;
    if (url === toggle && init.method === 'POST') {
      mutated = true;
      return raw(`<view xmlns="${HV}" xmlns:app="${NS}" id="task-row"><app:realtime-page request-id="${id}" page="1"/><text>A task completed</text></view>`, A);
    }
    if (url === ORIGIN + '/hv/login/' && init.method === 'POST') {
      logins += 1;
      acceptedB = logins === 2;
      const binding = acceptedB ? B : A;
      f.setBinding(binding, true);
      return raw(loginTransition, binding, 200, 'password-ok');
    }
    if (url === ORIGIN + '/hv/dashboard/') return raw(doc(id, true).replace('<text>Account B</text>', acceptedB ? '<text>Account B</text>' : '<view href="/hv/tasks/?status=active" action="navigate"><text>Open A Tasks Active</text></view>'), acceptedB ? B : A);
    if (url === tasks) return raw(doc(id, true).replace('<text>Account B</text>', `<text>A Tasks Active</text><view id="task-row"><view href="${toggle}" action="replace" verb="post" target="task-row"><text>Complete A task</text></view></view>`), A);
    if (url.startsWith(ORIGIN + '/hv/recovery/')) {
      if (new Headers(init.headers).get('X-HyperTodo-Recovery') !== 'login-v1') {
        // Exact backend envelope for recovery without its presentation selector.
        const response = new Response('{"error":"recovery-required"}', {status:404, headers:{'Content-Type':'application/json'}});
        Object.defineProperty(response, 'url', {value:url});
        return response;
      }
      if (url === ORIGIN + '/hv/recovery/') return raw(rootTemplate.replace('{{ route_id }}', 'root-route').replace('{{ route_href }}', '/hv/recovery/?screen=login'), C);
      if (url === ORIGIN + '/hv/recovery/?screen=login') return raw(doc(id, false).replace('<text>Login</text>', '<text>Neutral Login</text>'), C);
    }
    return undefined;
  });
  const add = AppState.addEventListener;
  const spy = jest.fn((...args:Parameters<typeof add>) => add(...args));
  AppState.addEventListener = spy;
  const onError = jest.fn();
  const ActualApp = createSessionApp(f.options, createThemeStore({read:()=> 'light',write:()=>{}}), {onError, logger:{error:()=>{},warn:()=>{},info:()=>{},log:()=>{}}});
  const ui = render(<ActualApp />);
  const state = (next:'inactive'|'active') => {
    for (const [event, callback] of spy.mock.calls) if (event === 'change') callback(next);
  };
  try {
    fireEvent(ui.getByTestId('animated-splash'), 'layout');
    await ui.findByText('Login');
    fireEvent.press(ui.getByText('Sign in'));
    await ui.findByText('Open A Tasks Active');
    expect(f.save).toHaveBeenCalledTimes(1);
    fireEvent.press(ui.getByText('Open A Tasks Active'));
    await ui.findByText('A Tasks Active');
    fireEvent.press(ui.getByText('Complete A task'));
    await ui.findByText('A task completed');
    expect(mutated).toBe(true);
    await act(async () => state('inactive'));
    f.setBinding(C, false);
    await act(async () => state('active'));
    await ui.findByText('We could not confirm your session');
    expect(ui.queryByText('A Tasks Active')).toBeNull();
    fireEvent.press(ui.getByRole('button', {name:'Sign in'}));
    await ui.findByText('Neutral Login');
    fireEvent.press(ui.getByText('Sign in'));
    await waitFor(() => expect(f.save).toHaveBeenCalledTimes(2));
    await ui.findByText('Account B');
    expect(onError).not.toHaveBeenCalled();
    expect(ui.queryByLabelText('Session protection')).toBeNull();
    expect(ui.queryByText('Neutral Login')).toBeNull();
  } finally {
    ui.unmount();
    AppState.addEventListener = add;
  }
});
