import 'react-native-gesture-handler/jestSetup';
import React from 'react';
import { AppState, StyleSheet, Text, TextInput, View } from 'react-native';
import { act, fireEvent, render } from '@testing-library/react-native';
import { SafeAreaInsetsContext, SafeAreaProvider } from 'react-native-safe-area-context';
import * as SecureStore from 'expo-secure-store';
import { createSessionApp } from '../App';
import { createNativeAppRunner } from '../test-support/native-app/runner';

// Real public provider/context/hooks; only its native layout event is supplied by
// this JS test. The App factory is a stateful lifecycle witness, not native proof.
jest.mock('react-native-safe-area-context', () => ({
  ...jest.requireActual('react-native-safe-area-context'),
  initialWindowMetrics: {
    frame: { x: 0, y: 0, width: 390, height: 844 },
    insets: { top: 59, left: 3, right: 11, bottom: 34 },
  },
}));
jest.mock('../App', () => ({ createSessionApp: jest.fn() }));
// Public Hyperview error exports load the SDK; retain its existing native WebView shim.
jest.mock('react-native-webview', () => ({ WebView: () => null }));
jest.mock('../src/behaviors/owned-native', () => ({ createOwnedNativePorts: jest.fn(() => ({})) }));
const config = {
  run: 'a'.repeat(32),
  apiOrigin: `http://hvt-${'a'.repeat(32)}.local:8787`,
  metroOrigin: `http://hvtm-${'a'.repeat(32)}.local:8082`,
  credentialKey: `hvt-native-${'a'.repeat(32)}.credential`,
  themeKey: `hvt-native-${'a'.repeat(32)}.theme`,
};
let mounts = 0;
let unmounts = 0;
let shellContextInApp: unknown;
const originalAppState = AppState.currentState;
afterEach(() => { AppState.currentState = originalAppState; });
beforeEach(() => {
  AppState.currentState = 'active';
  jest.restoreAllMocks();
  jest.clearAllMocks();
  mounts = 0; unmounts = 0; shellContextInApp = undefined;
  jest.spyOn(SecureStore, 'getItemAsync').mockResolvedValue(null);
  jest.spyOn(SecureStore, 'getItem').mockReturnValue(null);
  jest.spyOn(SecureStore, 'setItemAsync').mockResolvedValue(undefined);
  jest.spyOn(SecureStore, 'deleteItemAsync').mockResolvedValue(undefined);
  jest.mocked(createSessionApp).mockImplementation(() => function RetainedApp() {
    const [draft, setDraft] = React.useState('');
    shellContextInApp = React.useContext(SafeAreaInsetsContext);
    React.useEffect(() => { mounts++; return () => { unmounts++; }; }, []);
    return <View><Text>Actual factory witness</Text><TextInput accessibilityLabel="Retained draft" value={draft} onChangeText={setDraft} /></View>;
  });
});
function controls(screen: ReturnType<typeof render>) {
  return screen.UNSAFE_getAllByType(View).find(node => StyleSheet.flatten(node.props.style)?.backgroundColor === '#f0f0f0')!;
}
function paddings(screen: ReturnType<typeof render>) {
  const style = StyleSheet.flatten(controls(screen).props.style);
  return {
    top: style.paddingTop ?? style.paddingVertical ?? style.padding ?? 0,
    left: style.paddingLeft ?? style.paddingHorizontal ?? style.padding ?? 0,
    right: style.paddingRight ?? style.paddingHorizontal ?? style.padding ?? 0,
    bottom: style.paddingBottom ?? style.paddingVertical ?? style.padding ?? 0,
  };
}
function changeInsets(screen: ReturnType<typeof render>, insets: { top: number; left: number; right: number; bottom: number }) {
  const provider = screen.UNSAFE_getByType(SafeAreaProvider);
  const native = provider.find(node => typeof node.props.onInsetsChange === 'function');
  act(() => native.props.onInsetsChange({ nativeEvent: { frame: { x: 0, y: 0, width: 844, height: 390 }, insets } }));
}
function fixture() {
  const http = jest.fn(async () => new Response(null, { status: 204 }));
  const Runner = createNativeAppRunner(config, 'ios', http);
  return { screen: render(<Runner />), http };
}

it('places fixture controls below the real top inset with horizontal cutout clearance and existing spacing', () => {
  const { screen } = fixture();
  expect(paddings(screen)).toEqual({ top: 67, left: 11, right: 19, bottom: 8 });
  expect(screen.getByRole('header')).toHaveTextContent('Native real-App fixture — startup');
  expect(screen.getByRole('button', { name: 'Next case' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Receive tasks hint' })).toBeDisabled();
  // App keeps its own SafeAreaProvider: the shell provider is not its ancestor.
  expect(shellContextInApp).toBeNull();
  screen.unmount();
});

it('uses only the existing eight-pixel spacing on a zero-inset display', () => {
  const { screen } = fixture();
  expect(paddings(screen).top).toBe(67);
  changeInsets(screen, { top: 0, left: 0, right: 0, bottom: 0 });
  expect(paddings(screen)).toEqual({ top: 8, left: 8, right: 8, bottom: 8 });
  expect(mounts).toBe(1);
  screen.unmount();
});

it('updates insets without remounting App, discarding its draft, inventing records or changing control cleanup', async () => {
  const { screen, http } = fixture();
  expect(paddings(screen).top).toBe(67);
  fireEvent.changeText(screen.getByLabelText('Retained draft'), 'unchanged draft');
  const options = jest.mocked(createSessionApp).mock.calls[0][0];
  const hint = jest.fn(() => true);
  act(() => options.onResourceReceiver?.(hint));
  const before = http.mock.calls.length;
  changeInsets(screen, { top: 0, left: 59, right: 21, bottom: 21 });
  expect(paddings(screen)).toEqual({ top: 8, left: 67, right: 29, bottom: 8 });
  expect(screen.getByLabelText('Retained draft')).toHaveDisplayValue('unchanged draft');
  expect(mounts).toBe(1); expect(unmounts).toBe(0);
  expect(http.mock.calls.length).toBe(before);
  expect(shellContextInApp).toBeNull();
  fireEvent.press(screen.getByRole('button', { name: 'Receive tasks hint' }));
  expect(hint).toHaveBeenCalledTimes(1);
  expect(hint).toHaveBeenCalledWith(['tasks']);
  fireEvent.press(screen.getByRole('button', { name: 'Next case' }));
  expect(screen.getByRole('header')).toHaveTextContent('Native real-App fixture — auth');
  changeInsets(screen, { top: 59, left: 0, right: 0, bottom: 34 });
  expect(screen.getByLabelText('Retained draft')).toHaveDisplayValue('unchanged draft');
  expect(mounts).toBe(1);
  fireEvent.press(screen.getByRole('button', { name: 'Finish and clean fixture' }));
  await screen.findByText('Evidence complete — host review required');
  expect(unmounts).toBe(1);
  expect(screen.getByRole('button', { name: 'Finish and clean fixture' })).toBeDisabled();
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledTimes(2);
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith(config.credentialKey);
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith(config.themeKey);
  screen.unmount();
});
