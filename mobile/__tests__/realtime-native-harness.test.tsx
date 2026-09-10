import "react-native-gesture-handler/jestSetup";
import React from 'react';
import { Text, AppState } from 'react-native';
import { act, fireEvent, render, waitFor } from '@testing-library/react-native';
import * as SecureStore from 'expo-secure-store';
import { createSessionApp } from '../App';
import { createNativeAppRunner } from '../test-support/native-app/runner';
// These are fixture DI/control tests, not native evidence. App itself has real-SDK suites.
jest.mock('../App', () => {
  const React = require('react');
  const {
    Text
  } = require('react-native');
  return {
    createSessionApp: jest.fn(() => () => React.createElement(Text, null, 'Actual App factory component'))
  };
});
jest.mock('../src/behaviors/owned-native', () => ({
  createOwnedNativePorts: jest.fn(() => ({}))
}));
jest.mock("expo-splash-screen", () => ({
  preventAutoHideAsync: jest.fn(),
  hideAsync: jest.fn()
}));
jest.mock("lottie-react-native", () => {
  const React = require("react"),
    {
      View
    } = require("react-native");
  return {
    __esModule: true,
    default: React.forwardRef((props: any, ref: any) => {
      React.useImperativeHandle(ref, () => ({
        play: () => props.onAnimationFinish?.(false),
        reset: () => {}
      }));
      return React.createElement(View, props);
    })
  };
});
jest.mock("react-native-safe-area-context", () => jest.requireActual("react-native-safe-area-context/jest/mock").default);
jest.mock("react-native-webview", () => ({
  WebView: () => null
}));
const actualApp = jest.requireActual('../App');
const config = {
  run: 'a'.repeat(32),
  apiOrigin: `http://hvt-${'a'.repeat(32)}.local:8787`,
  metroOrigin: `http://hvtm-${'a'.repeat(32)}.local:8082`,
  credentialKey: `hvt-native-${'a'.repeat(32)}.credential`,
  themeKey: `hvt-native-${'a'.repeat(32)}.theme`
};
const originalAppState = AppState.currentState;
afterEach(() => { AppState.currentState = originalAppState; jest.useRealTimers(); });
beforeEach(() => {
  AppState.currentState = 'active';
  jest.restoreAllMocks();
  jest.clearAllMocks();
  jest.spyOn(SecureStore, 'getItemAsync').mockResolvedValue(null);
  jest.spyOn(SecureStore, 'getItem').mockReturnValue(null);
  jest.spyOn(SecureStore, 'setItemAsync').mockResolvedValue(undefined);
  jest.spyOn(SecureStore, 'deleteItemAsync').mockResolvedValue(undefined);
});
it('uses the actual factory with isolated credential/theme ports and safe diagnostics', async () => {
  const http = jest.fn(async () => ({
    status: 204
  }) as Response);
  const App = createNativeAppRunner(config, 'ios', http);
  expect(SecureStore.getItemAsync).not.toHaveBeenCalled();
  expect(SecureStore.getItem).not.toHaveBeenCalled();
  const [options,, diagnostics] = jest.mocked(createSessionApp).mock.calls[0];
  expect(options.entrypointUrl).toBe(config.apiOrigin + '/hv/');
  expect(diagnostics).toBeDefined();
  const screen = render(<App />);
  expect(screen.getByText('Actual App factory component')).toBeTruthy();
  await options.credentials.read();
  expect(SecureStore.getItemAsync).toHaveBeenCalledWith(config.credentialKey);
  let hints = 0;
  act(() => options.onResourceReceiver?.(() => {
    hints++;
    return true;
  }));
  fireEvent.press(screen.getByRole('button', {
    name: 'Receive tasks hint'
  }));
  expect(hints).toBe(1);
  act(() => {
    diagnostics!.onError(new Error('private header text'));
    diagnostics!.logger.error('secret payload');
  });
  await waitFor(() => expect(http.mock.calls.length).toBeGreaterThan(0));
  for (const call of http.mock.calls as unknown as [string, RequestInit][]) {
    expect(call[0]).toBe(config.apiOrigin + '/__native__/report/');
    expect(String(call[1].body)).not.toMatch(/private|secret/);
  }
  fireEvent.press(screen.getByRole('button', {
    name: 'Finish and clean fixture'
  }));
  await screen.findByText('Evidence complete — host review required');
  expect(screen.getByText('Local cleanup: confirmed')).toBeTruthy();
  expect(screen.getByText('Report: complete (none)')).toBeTruthy();
  expect(screen.queryByText('Actual App factory component')).toBeNull();
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith(config.credentialKey);
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith(config.themeKey);
  screen.unmount();
});
it('unmounts the real App factory component before deleting its own storage', async () => {
  const order: string[] = [];
  jest.mocked(createSessionApp).mockImplementationOnce(() => () => {
    React.useEffect(() => () => {
      order.push('unmounted');
    }, []);
    return <Text>App</Text>;
  });
  jest.mocked(SecureStore.deleteItemAsync).mockImplementation(async () => {
    order.push('delete');
  });
  const App = createNativeAppRunner(config, 'ios', async () => ({
    status: 204
  }) as Response);
  const screen = render(<App />);
  fireEvent.press(screen.getByRole('button', {
    name: 'Finish and clean fixture'
  }));
  await screen.findByText('Evidence complete — host review required');
  expect(order[0]).toBe('unmounted');
  screen.unmount();
});
it('revokes the actual App source receiver before fixture key deletion', async () => {
  const original = AppState.currentState;
  AppState.currentState = 'active';
  let receive: ((names: readonly any[]) => boolean) | null = null;
  const order: string[] = [];
  jest.mocked(createSessionApp).mockImplementationOnce((options, theme, diagnostics) => actualApp.createSessionApp({
    ...options,
    onResourceReceiver: (value: any) => {
      options.onResourceReceiver?.(value);
      if (value) receive = value;else if (receive) order.push(receive(['tasks']) ? 'still-live' : 'revoked');
    }
  }, theme, diagnostics));
  jest.mocked(SecureStore.deleteItemAsync).mockImplementation(async () => {
    order.push('delete');
  });
  const HV = 'https://hyperview.org/hyperview',
    NS = 'https://hypertodo.app/components',
    binding = 'hvs1.' + 'A'.repeat(43);
  const http = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith('/__native__/report/')) return new Response(null, {
      status: 204
    });
    const id = new Headers(init?.headers).get('X-HyperTodo-Request-ID');
    const body = url.endsWith('/session-state/') ? JSON.stringify({
      version: 1,
      authenticated: false,
      binding
    }) : url.endsWith('/hv/') ? `<doc xmlns="${HV}"><navigator id="root" type="stack"><nav-route id="tasks" href="/hv/tasks/"/></navigator></doc>` : `<doc xmlns="${HV}" xmlns:app="${NS}"><screen><body><app:realtime mode="notice" target="main" refresh-href="/hv/tasks/" resources="tasks"><view id="main"><app:realtime-page request-id="${id}" page="1"/><text>Actual SDK App screen</text></view></app:realtime></body></screen></doc>`;
    const response = new Response(body, {
      headers: {
        'X-HyperTodo-Session-Binding': binding,
        'Content-Type': 'application/vnd.hyperview+xml'
      }
    });
    Object.defineProperty(response, 'url', {
      value: url
    });
    return response;
  };
  const App = createNativeAppRunner(config, 'ios', http);
  const screen = render(<App />);
  try {
    fireEvent(screen.getByTestId('animated-splash'), 'layout');
    await screen.findByText('Actual SDK App screen');
    await waitFor(() => expect(receive).not.toBeNull());
    order.length = 0;
    fireEvent.press(screen.getByRole('button', {
      name: 'Finish and clean fixture'
    }));
    await screen.findByText('Evidence complete — host review required');
    expect(order.indexOf('revoked')).toBeGreaterThanOrEqual(0);
    expect(order.indexOf('revoked')).toBeLessThan(order.indexOf('delete'));
    expect(order).not.toContain('still-live');
  } finally {
    screen.unmount();
    AppState.currentState = original;
  }
});

// Deliberate test failures describe local diagnostic semantics, not the physical
// cause of any previous phone recording gap. Reporter/lifetime policies stay real.
it('separates confirmed local cleanup from a failed report without leaking the failure', async () => {
  const http = jest.fn(async () => { throw new Error('synthetic-private-header-token'); });
  const App = createNativeAppRunner(config, 'ios', http);
  const screen = render(<App />);
  fireEvent.press(screen.getByRole('button', { name: 'Finish and clean fixture' }));
  await screen.findByText('INCONCLUSIVE — retain evidence for review');
  expect(screen.getByText('Local cleanup: confirmed')).toBeTruthy();
  expect(screen.getByText('Report: inconclusive (report-failed)')).toBeTruthy();
  expect(screen.queryByText('Actual App factory component')).toBeNull();
  expect(screen.getByRole('button', { name: 'Finish and clean fixture' })).toBeDisabled();
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledTimes(2);
  expect(http).toHaveBeenCalledTimes(2); // The second transport failure exhausts this same head.
  expect(JSON.stringify(screen.toJSON())).not.toMatch(/synthetic-private|header-token|hvt-native/);
  screen.unmount();
});
it('does not infer local cleanup from a successful upload when native key removal fails', async () => {
  jest.mocked(SecureStore.deleteItemAsync).mockRejectedValue(new Error('synthetic-private-storage-key'));
  const uploads: unknown[] = [];
  const http = jest.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    uploads.push(JSON.parse(String(init?.body)));
    return new Response(null, { status: 204 });
  });
  const App = createNativeAppRunner(config, 'ios', http);
  const screen = render(<App />);
  fireEvent.press(screen.getByRole('button', { name: 'Finish and clean fixture' }));
  await screen.findByText('INCONCLUSIVE — retain evidence for review');
  expect(screen.getByText('Local cleanup: not confirmed')).toBeTruthy();
  expect(screen.getByText('Report: inconclusive (cleanup-failed)')).toBeTruthy();
  expect(screen.queryByText('Local cleanup: confirmed')).toBeNull();
  expect(screen.queryByText('Actual App factory component')).toBeNull();
  expect(http).toHaveBeenCalledTimes(1);
  expect(uploads).toEqual([expect.objectContaining({ kind: 'inconclusive', reason: 'cleanup-failed' })]);
  expect(JSON.stringify(screen.toJSON())).not.toMatch(/synthetic-private|storage-key|hvt-native/);
  screen.unmount();
});

// Public AppState notifications plus injected transport outcomes: not phone-cause evidence.
it('does not assume active at startup and admits queued reports only after confirmed active', async () => {
  AppState.currentState = null as unknown as typeof AppState.currentState;
  let change!: (state: typeof AppState.currentState) => void;
  const remove = jest.fn();
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, callback) => { change = callback; return { remove }; });
  const records: { kind: string }[] = [];
  const http = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
    records.push(JSON.parse(String(init?.body))); return new Response(null, { status: 204 });
  });
  const Runner = createNativeAppRunner(config, 'ios', http), screen = render(<Runner />);
  const diagnostics = jest.mocked(createSessionApp).mock.calls[0][2]!;
  await act(async () => { diagnostics.onError(new Error('discarded private value')); });
  expect(http).not.toHaveBeenCalled();
  await act(async () => { change('active'); });
  expect(records.map(record => record.kind)).toEqual(['diagnostic', 'foreground']);
  fireEvent.press(screen.getByRole('button', { name: 'Finish and clean fixture' }));
  await screen.findByText('Evidence complete — host review required');
  screen.unmount(); expect(remove).toHaveBeenCalledTimes(1);
});
it('queues inactive/background across five seconds and preserves foreground/Finish order', async () => {
  jest.useFakeTimers();
  let phase: typeof AppState.currentState = 'active', change!: (state: typeof phase) => void;
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, callback) => { change = callback; return { remove: jest.fn() }; });
  const records: { kind: string; sequence: number }[] = [];
  const http = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
    expect(phase).toBe('active');
    expect(Object.keys(init?.headers || {})).toEqual(['Content-Type']);
    expect(init?.signal).toBeInstanceOf(AbortSignal);
    records.push(JSON.parse(String(init?.body))); return new Response(null, { status: 204 });
  });
  const Runner = createNativeAppRunner(config, 'ios', http), screen = render(<Runner />);
  await act(async () => { phase = 'inactive'; change(phase); });
  await act(async () => { phase = 'background'; change(phase); await jest.advanceTimersByTimeAsync(5000); });
  expect(http).not.toHaveBeenCalled();
  await act(async () => { phase = 'active'; change(phase); });
  fireEvent.press(screen.getByRole('button', { name: 'Finish and clean fixture' }));
  await screen.findByText('Evidence complete — host review required');
  expect(records.map(record => record.kind)).toEqual(['paused', 'paused', 'foreground', 'cleanup', 'complete']);
  expect(records.map(record => record.sequence)).toEqual([1, 2, 3, 4, 5]);
  expect(screen.getByText('Local cleanup: confirmed')).toBeTruthy(); screen.unmount();
});
it('unexpected unmount cancels an inactive report wait without upload or fake completion', async () => {
  AppState.currentState = 'background';
  let change!: (state: typeof AppState.currentState) => void;
  const remove = jest.fn();
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, callback) => { change = callback; return { remove }; });
  const http = jest.fn(async () => new Response(null, { status: 204 }));
  const Runner = createNativeAppRunner(config, 'ios', http), screen = render(<Runner />);
  await act(async () => { change('background'); });
  screen.unmount(); await act(async () => { change('active'); });
  expect(remove).toHaveBeenCalledTimes(1); expect(http).not.toHaveBeenCalled();
});
it('reads current AppState after subscription, not an active value captured before mount', async () => {
  jest.mocked(createSessionApp).mockImplementationOnce(options => function LayoutWitness() {
    React.useLayoutEffect(() => {
      options.onGateObservation?.({ kind: 'ready', epoch: 0, routeKey: 'fixture-route' });
    }, []);
    return <Text>Layout witness</Text>;
  });
  let change!: (state: typeof AppState.currentState) => void;
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, callback) => { change = callback; return { remove: jest.fn() }; });
  const http = jest.fn(async () => new Response(null, { status: 204 }));
  const Runner = createNativeAppRunner(config, 'ios', http); // Actual state is active here.
  AppState.currentState = 'background';
  const screen = render(<Runner />);
  await act(async () => {});
  expect(http).not.toHaveBeenCalled(); // Child layout must not use factory-time activity.
  await act(async () => { change('active'); });
  expect(http).toHaveBeenCalledTimes(2); // Actual ready then foreground, not fabricated ACK.
  screen.unmount();
});

async function parserDiagnosticError(status = 503): Promise<Error> {
  const { Parser } = jest.requireActual('hyperview');
  const response = new Response('private-body-value', {status, headers:{'Content-Type':'application/json','private-header':'private-header-value'}});
  Object.defineProperty(response, 'url', {value:'https://private-url.invalid/'});
  try {
    await new Parser(async () => response).loadDocument('https://private-url.invalid/');
  } catch (error) {
    return error as Error;
  }
  throw new Error('Expected genuine SDK parser error');
}

it('keeps first closed SDK classifications separately by sink and after fixture cleanup', async () => {
  const error = await parserDiagnosticError();
  const { HvBaseError } = jest.requireActual('hyperview');
  expect(error).toBeInstanceOf(HvBaseError);
  const http = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(null, {status:204}));
  const App = createNativeAppRunner(config, 'ios', http);
  const ui = render(<App />);
  const diagnostic = jest.mocked(createSessionApp).mock.calls[0][2]!;
  act(() => {
    diagnostic.onError(error);
    diagnostic.logger.error(error);
    diagnostic.logger.warn(error);
    diagnostic.onError(new Error('private-later-error'));
  });
  for (const sink of ['on-error','logger-error','logger-warn']) {
    expect(ui.getByText(`SDK ${sink}: http; status 503`)).toBeTruthy();
  }
  fireEvent.press(ui.getByRole('button', {name:'Finish and clean fixture'}));
  await ui.findByText('Local cleanup: confirmed');
  await ui.findByText('Evidence complete — host review required');
  expect(ui.getAllByText(/^SDK /)).toHaveLength(3);
  for (const sink of ['on-error','logger-error','logger-warn']) expect(ui.getByText(`SDK ${sink}: http; status 503`)).toBeTruthy();
  const payloads = http.mock.calls.map(([, init]) => JSON.parse(init!.body as string));
  expect(payloads.filter(record => record.kind === 'diagnostic')).toHaveLength(4);
  expect(payloads.filter(record => record.kind === 'diagnostic').every(record => record.reason === 'sdk-error')).toBe(true);
  expect(JSON.stringify(payloads)).not.toMatch(/private-|503|logger-warn|on-error/);
  ui.unmount();
});

it('does not classify arbitrary name/status spoofs or invoke diagnostic getters', async () => {
  const http = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(null, {status:204}));
  const App = createNativeAppRunner(config, 'ios', http);
  const ui = render(<App />);
  const diagnostic = jest.mocked(createSessionApp).mock.calls[0][2]!;
  const spoof = Object.assign(new Error('private-spoof'), {name:'ServerError',status:403});
  const getter = jest.fn(() => { throw new Error('private-getter'); });
  const sdk = await parserDiagnosticError();
  Object.defineProperties(sdk, {name:{get:getter},status:{get:getter},message:{get:getter},extraContext:{get:getter}});
  act(() => {
    diagnostic.onError(spoof);
    diagnostic.logger.error(sdk);
    diagnostic.logger.warn({name:'ServerError',status:401,message:'private-object'});
  });
  expect(getter).not.toHaveBeenCalled();
  for (const sink of ['on-error','logger-error','logger-warn']) expect(ui.getByText(`SDK ${sink}: unknown; status unknown`)).toBeTruthy();
  expect(JSON.stringify(ui.toJSON())).not.toMatch(/private-|403|401/);
  fireEvent.press(ui.getByRole('button', {name:'Finish and clean fixture'}));
  await ui.findByText('Evidence complete — host review required');
  expect(JSON.stringify(http.mock.calls)).not.toMatch(/private-|403|401/);
  expect(getter).not.toHaveBeenCalled();
  ui.unmount();
});

it('ignores invalid or accessor HTTP status while retaining a known SDK family code', async () => {
  const http = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(null, {status:204}));
  const App = createNativeAppRunner(config, 'ios', http);
  const ui = render(<App />);
  const diagnostic = jest.mocked(createSessionApp).mock.calls[0][2]!;
  const errors = await Promise.all([parserDiagnosticError(),parserDiagnosticError(),parserDiagnosticError()]);
  Object.defineProperty(errors[0], 'status', {value:700});
  Object.defineProperty(errors[1], 'status', {value:'403'});
  const getter = jest.fn(() => { throw new Error('private-status'); });
  Object.defineProperty(errors[2], 'status', {get:getter});
  act(() => {
    diagnostic.onError(errors[0]);
    diagnostic.logger.error(errors[1]);
    diagnostic.logger.warn(errors[2]);
  });
  for (const sink of ['on-error','logger-error','logger-warn']) expect(ui.getByText(`SDK ${sink}: http; status unknown`)).toBeTruthy();
  expect(getter).not.toHaveBeenCalled();
  fireEvent.press(ui.getByRole('button', {name:'Finish and clean fixture'}));
  await ui.findByText('Evidence complete — host review required');
  ui.unmount();
});
