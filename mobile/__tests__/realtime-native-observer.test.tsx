import "react-native-gesture-handler/jestSetup";
import React from "react";
import { Text } from "react-native";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { NavigationContainer } from "@react-navigation/native";
import { createStackNavigator } from "@react-navigation/stack";
import type { HvComponentProps } from "hyperview";
import { createRealtimeGate } from "../src/realtime/gate";
// The transport is controlled in Jest; parser, public callbacks/navigation/layout are real SDK.
const {
  validateRecord
} = require('../test-support/native-app/report.cjs');
jest.mock('react-native-webview', () => ({
  WebView: () => null
}));
const Stack = createStackNavigator(),
  HV = 'https://hyperview.org/hyperview',
  APP = 'https://hypertodo.app/components';
const BASE = 'https://hypertodo.test/hv/tasks/';
const doc = (id: string, label = 'Initial') => `<doc xmlns="${HV}" xmlns:app="${APP}"><screen><body><app:realtime mode="notice" target="rows" refresh-href="/hv/tasks/"><list id="rows"><item key="one"><app:realtime-page request-id="${id}" page="1"/><text>${label}</text><app:watch/></item></list><app:rerender/><view href="/hv/tasks/" action="reload"><text>Reload</text></view><view href="/hv/tasks/more/" action="append" target="rows"><text>More</text></view><view id="local"><text>Local copy</text></view><view id="local-target"/><view href="#local" action="append" target="local-target"><text>Copy</text></view></app:realtime></body></screen></doc>`;
const response = (body: string, status = 200) => ({
  status,
  ok: status === 200,
  url: BASE,
  headers: new Headers(),
  text: async () => body
}) as Response;
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => {
    resolve = yes;
  });
  return {
    promise,
    resolve
  };
}
function setup(next?: (id: string) => Promise<Response>, throws = false) {
  const observed: any[] = [],
    during: any[] = [],
    parsed: any[] = [];
  const gate = createRealtimeGate({
    onObservation: (event: any) => {
      observed.push(event);
      if (throws) throw new Error('private observer error');
    }
  });
  const Watch = Object.assign(() => {
    during.push(observed.filter(e => e.kind === 'terminal').length);
    return null;
  }, {
    localName: 'watch',
    namespaceURI: APP
  });
  const Rerender = Object.assign(({
    options
  }: HvComponentProps) => <Text onPress={() => options.onUpdateCallbacks!.setState({})}>Old render</Text>, {
    localName: 'rerender',
    namespaceURI: APP
  });
  const transport = jest.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    const id = new Headers(init?.headers).get('X-HyperTodo-Request-ID')!;
    if (transport.mock.calls.length === 1) return response(doc(id));
    return next ? next(id) : response(doc(id, 'Fresh'));
  });
  const screen = render(<NavigationContainer><Stack.Navigator screenOptions={{
      animationEnabled: false
    }}><Stack.Screen name="fixture">{() => <gate.Root entrypointUrl={BASE} fetch={gate.wrapFetch(transport)} onParseAfter={() => {
          parsed.push(observed.filter(e => e.kind === 'terminal').length);
        }} formatDate={() => undefined} onError={() => {}} components={[...gate.components, Watch, Rerender]} />}</Stack.Screen></Stack.Navigator></NavigationContainer>);
  return {
    gate,
    screen,
    transport,
    observed,
    during,
    parsed
  };
}
it('reports immutable real focused readiness and only a committed correlated reload', async () => {
  const x = setup();
  try {
    await x.screen.findByText('Initial');
    expect(x.observed).toHaveLength(1);
    expect(x.observed[0]).toEqual({
      kind: 'ready',
      epoch: 0,
      routeKey: expect.any(String)
    });
    expect(Object.isFrozen(x.observed[0])).toBe(true);
    x.during.length = 0;
    x.parsed.length = 0;
    fireEvent.press(x.screen.getByText('Reload'));
    await x.screen.findByText('Fresh');
    const terminal = x.observed[1];
    expect(terminal).toEqual({
      kind: 'terminal',
      epoch: 0,
      routeKey: x.observed[0].routeKey,
      operation: new Headers(x.transport.mock.calls[1][1]?.headers).get('X-HyperTodo-Request-ID'),
      outcome: 'ack',
      reason: 'reload-layout'
    });
    expect(Object.isFrozen(terminal)).toBe(true);
    expect(x.during).toContain(0);
    expect(x.parsed).toContain(0);
    expect(x.gate.snapshot().operations).toBe(0);
    const wire = {
      v: 1,
      run: 'a'.repeat(32),
      sequence: 1,
      platform: 'ios',
      case: 'resources',
      kind: 'terminal',
      operation: terminal.operation,
      route: 1,
      outcome: terminal.outcome,
      reason: terminal.reason
    };
    expect(validateRecord(wire, wire.run, 1)).toEqual(wire);
  } finally {
    x.screen.unmount();
  }
});
it('cannot report a pending body or old render as ACK', async () => {
  const held = deferred<Response>();
  let id = '';
  const x = setup(async value => {
    id = value;
    return held.promise;
  });
  try {
    await x.screen.findByText('Initial');
    fireEvent.press(x.screen.getByText('Reload'));
    await waitFor(() => expect(x.transport).toHaveBeenCalledTimes(2));
    await act(async () => fireEvent.press(x.screen.getByText('Old render')));
    expect(x.observed.filter(e => e.kind === 'terminal')).toHaveLength(0);
    expect(x.gate.snapshot().operations).toBe(1);
    await act(async () => held.resolve(response(doc(id, 'Fresh'))));
    await x.screen.findByText('Fresh');
    expect(x.observed.filter(e => e.outcome === 'ack')).toHaveLength(1);
  } finally {
    x.screen.unmount();
  }
});
it('contains observer exceptions without suppressing retirement or a subsequent operation', async () => {
  const x = setup(undefined, true);
  try {
    await x.screen.findByText('Initial');
    fireEvent.press(x.screen.getByText('Reload'));
    await x.screen.findByText('Fresh');
    fireEvent.press(x.screen.getByText('Reload'));
    await waitFor(() => expect(x.transport).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(x.observed.filter(e => e.outcome === 'ack')).toHaveLength(2));
    expect(x.gate.snapshot().operations).toBe(0);
  } finally {
    x.screen.unmount();
  }
});
it.each(['empty', 'error', 'abort'])('reports truthful %s terminal without an ACK', async kind => {
  const x = setup(async () => {
    if (kind === 'empty') return response('', 204);
    const error = new Error('private wire detail');
    if (kind === 'abort') error.name = 'AbortError';
    throw error;
  });
  try {
    await x.screen.findByText('Initial');
    fireEvent.press(x.screen.getByText('More'));
    await waitFor(() => expect(x.gate.snapshot().operations).toBe(0));
    expect(x.observed.at(-1)).toMatchObject({
      kind: 'terminal',
      outcome: kind === 'empty' ? 'no-document' : kind === 'abort' ? 'cancelled' : 'error'
    });
    expect(JSON.stringify(x.observed)).not.toContain('private');
    expect(x.observed.some(e => e.outcome === 'ack')).toBe(false);
  } finally {
    x.screen.unmount();
  }
});
it('reports a local layout without fabricating a wire request ID', async () => {
  const x = setup();
  try {
    await x.screen.findByText('Initial');
    fireEvent.press(x.screen.getByText('Copy'));
    await waitFor(() => expect(x.observed.at(-1)).toMatchObject({
      kind: 'terminal',
      operation: null,
      outcome: 'ack',
      reason: 'local-layout'
    }));
    expect(x.transport).toHaveBeenCalledTimes(1);
  } finally {
    x.screen.unmount();
  }
});
