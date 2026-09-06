import React from "react";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { AccessibilityInfo, Text } from "react-native";
import * as SplashScreen from "expo-splash-screen";

const mockPlay = jest.fn();
const mockReset = jest.fn();

jest.mock("expo-splash-screen", () => ({ preventAutoHideAsync: jest.fn(), hideAsync: jest.fn() }));
jest.mock("lottie-react-native", () => {
  const { forwardRef, useImperativeHandle } = require("react");
  const { View } = require("react-native");
  return {
    __esModule: true,
    default: forwardRef((props: any, ref: any) => {
      useImperativeHandle(ref, () => ({ play: mockPlay, reset: mockReset }));
      return <View {...props} testID="lottie" />;
    }),
  };
});

import AnimatedSplash from "../src/components/AnimatedSplash";

function renderSplash() {
  return render(
    <AnimatedSplash>
      <Text>App content</Text>
    </AnimatedSplash>,
  );
}

function layout(screen: ReturnType<typeof renderSplash>): void {
  fireEvent(screen.getByTestId("animated-splash"), "layout", {
    nativeEvent: { layout: { x: 0, y: 0, width: 360, height: 800 } },
  });
}

describe("AnimatedSplash", () => {
  beforeEach(() => {
    mockPlay.mockClear();
    mockReset.mockClear();
    (SplashScreen.hideAsync as jest.Mock).mockClear();
  });

  it("renders the overlay on top of the full-size children", () => {
    const screen = renderSplash();

    expect(screen.getByTestId("animated-splash")).toBeTruthy();
    // The app is mounted underneath but hidden from assistive technology while the splash is up.
    expect(screen.getByText("App content", { includeHiddenElements: true })).toBeTruthy();
    expect(screen.queryByText("App content")).toBeNull();
  });

  it("hides the native splash and starts playback exactly once, even if layout fires again", () => {
    const screen = renderSplash();

    layout(screen);
    layout(screen);

    expect(SplashScreen.hideAsync).toHaveBeenCalledTimes(1);
    expect(mockPlay).toHaveBeenCalledTimes(1);
  });

  it("removes the overlay when the animation finishes, keeping children mounted", () => {
    const screen = renderSplash();

    fireEvent(screen.getByTestId("lottie"), "animationFinish", false);

    expect(screen.queryByTestId("animated-splash")).toBeNull();
    expect(screen.getByText("App content")).toBeTruthy();
  });

  it("removes the overlay when the animation is cancelled or fails to load", () => {
    const cancelled = renderSplash();
    fireEvent(cancelled.getByTestId("lottie"), "animationFinish", true);
    expect(cancelled.queryByTestId("animated-splash")).toBeNull();

    const failed = renderSplash();
    fireEvent(failed.getByTestId("lottie"), "animationFailure", "could not load composition");
    expect(failed.queryByTestId("animated-splash")).toBeNull();
    expect(SplashScreen.hideAsync).toHaveBeenCalled();
  });

  it("falls back to a timer so the app is never stuck behind the overlay", () => {
    jest.useFakeTimers();
    try {
      const screen = renderSplash();

      act(() => {
        jest.advanceTimersByTime(2500);
      });

      expect(screen.queryByTestId("animated-splash")).toBeNull();
      expect(screen.getByText("App content")).toBeTruthy();
    } finally {
      jest.useRealTimers();
    }
  });

  it("skips the animation when the user prefers reduced motion", async () => {
    const spy = jest.spyOn(AccessibilityInfo, "isReduceMotionEnabled").mockResolvedValue(true);
    try {
      const screen = renderSplash();

      await waitFor(() => expect(screen.queryByTestId("animated-splash")).toBeNull());
      expect(SplashScreen.hideAsync).toHaveBeenCalled();
    } finally {
      spy.mockRestore();
    }
  });
});
