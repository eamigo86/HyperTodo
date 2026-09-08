import React from "react";
import { act, fireEvent, render } from "@testing-library/react-native";
import { ActivityIndicator, StyleSheet } from "react-native";

import App, { ErrorScreen, LoadingScreen } from "../App";
import ElementErrorBanner from "../src/components/ElementErrorBanner";
import OfflineRefreshControl from "../src/components/OfflineRefreshControl";
import { FAILURE_COPY } from "../src/feedback/failure";
import { hyperviewLogger, reportHyperviewError } from "../src/feedback/logging";
import { publishTheme } from "../src/theme";

jest.mock("expo-secure-store", () => ({ getItem: () => null, setItem: () => undefined }));
jest.mock("expo-splash-screen", () => ({ preventAutoHideAsync: jest.fn(), hideAsync: jest.fn() }));
// Capture the props instead of discarding them: dropping a behavior or the
// refreshControl from App.tsx is a silent, type-clean regression otherwise, and the
// symptom on device is a dead button or a spinner that never stops.
const mockHyperviewProps: Record<string, unknown> = {};
jest.mock("hyperview", () => (props: Record<string, unknown>) => {
  Object.assign(mockHyperviewProps, props);
  return null;
});
jest.mock("lottie-react-native", () => {
  const { forwardRef, useImperativeHandle } = require("react");
  const { View } = require("react-native");
  return {
    __esModule: true,
    default: forwardRef((props: any, ref: any) => {
      useImperativeHandle(ref, () => ({ play: jest.fn(), reset: jest.fn() }));
      return <View {...props} testID="lottie" />;
    }),
  };
});
jest.mock("react-native-safe-area-context", () => {
  const { View } = jest.requireActual("react-native");
  return { SafeAreaProvider: View, SafeAreaView: View };
});
jest.mock("@react-navigation/native", () => ({ NavigationContainer: ({ children }: { children: React.ReactNode }) => children }));

describe("owned shell screens", () => {
  it("keeps the server-driven UI inside the device safe area", () => {
    const screen = render(<App />);
    expect(screen.getByLabelText("HyperTodo safe area", { includeHiddenElements: true })).toBeTruthy();
    expect(screen.getByTestId("animated-splash")).toBeTruthy();
  });

  it("hands hyperview every behavior and shell component the HXML depends on", () => {
    render(<App />);

    const behaviors = mockHyperviewProps.behaviors as { action: string }[];
    expect(behaviors.map((behavior) => behavior.action).sort()).toEqual([
      "biometric-unlock",
      "pick-avatar",
      "probe-biometrics",
      "show-snackbar",
      "store-biometric-token",
    ]);
    expect(mockHyperviewProps.loadingScreen).toBe(LoadingScreen);
    expect(mockHyperviewProps.errorScreen).toBe(ErrorScreen);
    expect(mockHyperviewProps.elementErrorComponent).toBe(ElementErrorBanner);
    expect(mockHyperviewProps.refreshControl).toBe(OfflineRefreshControl);
    expect(mockHyperviewProps.logger).toBe(hyperviewLogger);
    expect(mockHyperviewProps.onError).toBe(reportHyperviewError);
  });

  it("renders the branded loading state", () => {
    const screen = render(<LoadingScreen />);
    expect(screen.getByText("HyperTodo")).toBeTruthy();
    expect(screen.getByLabelText("Loading HyperTodo")).toBeTruthy();
  });

  it("renders an actionable error state without leaking the raw failure", () => {
    const reload = jest.fn();
    const screen = render(<ErrorScreen error={new Error("Backend unavailable")} onPressReload={reload} back={jest.fn()} onPressViewDetails={jest.fn()} />);
    expect(screen.getByText(FAILURE_COPY.server.title)).toBeTruthy();
    expect(screen.getByText(FAILURE_COPY.server.body)).toBeTruthy();
    expect(screen.queryByText("Backend unavailable")).toBeNull();
    expect(screen.queryByText("We could not load your tasks")).toBeNull();
    fireEvent.press(screen.getByRole("button", { name: "Try again" }));
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("renders offline copy when the device cannot reach the backend", () => {
    const offline = new Error("fetch failed: UnexpectedException: Could not connect to the server. (at ExpoModulesCore/Promise.swift:56)");
    const screen = render(<ErrorScreen error={offline} onPressReload={jest.fn()} back={jest.fn()} onPressViewDetails={jest.fn()} />);
    expect(screen.getByText(FAILURE_COPY.offline.title)).toBeTruthy();
    expect(screen.getByText(FAILURE_COPY.offline.body)).toBeTruthy();
    expect(JSON.stringify(screen.toJSON())).not.toContain("fetch failed");
    expect(JSON.stringify(screen.toJSON())).not.toContain("ExpoModulesCore");
  });

  it("keeps the error call to action legible and tappable", () => {
    const screen = render(<ErrorScreen error={null} onPressReload={jest.fn()} back={jest.fn()} onPressViewDetails={jest.fn()} />);
    expect(screen.getByText("Try again").props.style).toEqual(
      expect.objectContaining({ fontSize: 19, fontWeight: "700" }),
    );
    expect(screen.getByRole("button", { name: "Try again" }).props.style).toEqual(
      expect.objectContaining({ minHeight: 44 }),
    );
  });
});

// The shell paints what no HXML document can reach. Before src/theme.ts these five
// surfaces were light-palette hex literals, so a dark-mode account got a #F7F8FC
// home-indicator strip under a #0F1118 bottom navigation bar.
describe("the shell follows the palette the server named", () => {
  beforeEach(() => act(() => publishTheme("light")));
  afterEach(() => act(() => publishTheme("light")));

  const flat = (node: { props: Record<string, unknown> }) =>
    StyleSheet.flatten(node.props.style as never) as Record<string, string>;
  const bg = (node: { props: Record<string, unknown> }) => flat(node).backgroundColor;
  const ink = (node: { props: Record<string, unknown> }) => flat(node).color;

  it("paints both safe-area insets from the tokens the screen behind them uses", () => {
    const screen = render(<App />);

    expect(bg(screen.getByTestId("top-inset", { includeHiddenElements: true }))).toBe("#278CFF");
    expect(bg(screen.getByLabelText("HyperTodo safe area", { includeHiddenElements: true }))).toBe("#F7F8FC");

    act(() => publishTheme("dark"));

    // #0F1118 is theme.canvas, which is exactly what every screen's
    // `bottom-navigation-style` rule declares. That equality IS the fix.
    expect(bg(screen.getByTestId("top-inset", { includeHiddenElements: true }))).toBe("#1F6FD1");
    expect(bg(screen.getByLabelText("HyperTodo safe area", { includeHiddenElements: true }))).toBe("#0F1118");
  });

  it("hands Hyperview identical props across a palette flip", () => {
    // Hyperview is a PureComponent. Inline `behaviors={[...]}` or an inline
    // formatDate closure would fail its shallow compare on every theme change and
    // re-render the entire server-driven tree to repaint two insets.
    render(<App />);
    const before = { ...mockHyperviewProps };

    act(() => publishTheme("dark"));

    (["behaviors", "components", "formatDate", "fetch"] as const).forEach((prop) =>
      expect(mockHyperviewProps[prop]).toBe(before[prop]),
    );
  });

  it("repaints the loading state, spinner included", () => {
    const screen = render(<LoadingScreen />);

    expect(bg(screen.getByLabelText("Loading HyperTodo"))).toBe("#F7F8FC");
    expect(ink(screen.getByText("HyperTodo"))).toBe("#161A35");
    expect(screen.UNSAFE_getByType(ActivityIndicator).props.color).toBe("#278CFF");

    act(() => publishTheme("dark"));

    expect(bg(screen.getByLabelText("Loading HyperTodo"))).toBe("#0F1118");
    expect(ink(screen.getByText("HyperTodo"))).toBe("#F3F5FB");
    expect(screen.UNSAFE_getByType(ActivityIndicator).props.color).toBe("#7FB6FF");
  });

  it("repaints the full-screen failure state", () => {
    const screen = render(
      <ErrorScreen error={null} onPressReload={jest.fn()} back={jest.fn()} onPressViewDetails={jest.fn()} />,
    );

    expect(bg(screen.getByTestId("error-card"))).toBe("#FFFFFF");
    expect(ink(screen.getByText(FAILURE_COPY.server.title))).toBe("#161A35");
    expect(ink(screen.getByText(FAILURE_COPY.server.body))).toBe("#6D728A");
    expect(bg(screen.getByRole("button", { name: "Try again" }))).toBe("#278CFF");

    act(() => publishTheme("dark"));

    expect(bg(screen.getByTestId("error-card"))).toBe("#1A1D26");
    expect(ink(screen.getByText(FAILURE_COPY.server.title))).toBe("#F3F5FB");
    expect(ink(screen.getByText(FAILURE_COPY.server.body))).toBe("#A9AFC2");
    // White on #1F6FD1 is 4.94:1 -- dark IMPROVES on light's 3.34:1, which is why
    // the button label stays white in both palettes.
    expect(bg(screen.getByRole("button", { name: "Try again" }))).toBe("#1F6FD1");
    expect(ink(screen.getByText("Try again"))).toBe("#FFFFFF");
  });

  it("keeps the loading mark on the identity colours, which are palette-independent upstream", () => {
    const screen = render(<LoadingScreen />);
    const check = screen.getByText("✓");

    expect(ink(check)).toBe("#161A35");
    act(() => publishTheme("dark"));
    expect(ink(check)).toBe("#161A35");
  });
});
